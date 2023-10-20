import time
import dataclasses
import os
import random
import struct
import sys
from crcmod.predefined import mkPredefinedCrcFun
import tempfile
from typing import cast, Optional
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock

from spacepackets.cfdp import (
    ChecksumType,
    Direction,
    DirectiveType,
    PduConfig,
    PduType,
    TransmissionMode,
    NULL_CHECKSUM_U32,
    ConditionCode,
)
from spacepackets.cfdp.pdu import (
    DeliveryCode,
    MetadataPdu,
    MetadataParams,
    EofPdu,
    FileDataPdu,
    FileDeliveryStatus,
)
from spacepackets.cfdp.pdu.file_data import FileDataParams
from spacepackets.util import ByteFieldU16, ByteFieldU8
from tmtccmd.cfdp import (
    IndicationCfg,
    LocalEntityCfg,
    RemoteEntityCfgTable,
    RemoteEntityCfg,
)
from tmtccmd.cfdp.defs import CfdpState, TransactionId
from tmtccmd.cfdp.handler.dest import (
    DestHandler,
    PduIgnoredForDest,
    TransactionStep,
    FsmResult,
)
from tmtccmd.cfdp.user import TransactionFinishedParams, FileSegmentRecvdParams
from tmtccmd.cfdp.handler import NoRemoteEntityCfgFound

from .cfdp_fault_handler_mock import FaultHandler
from .cfdp_user_mock import CfdpUser
from .common import TestCheckTimerProvider


@dataclasses.dataclass
class FileInfo:
    rand_data: bytes
    file_size: int
    crc32: bytes


class TestCfdpDestHandler(TestCase):
    def setUp(self) -> None:
        self.indication_cfg = IndicationCfg(True, True, True, True, True, True)
        self.fault_handler = FaultHandler()
        self.entity_id = ByteFieldU16(2)
        self.local_cfg = LocalEntityCfg(
            self.entity_id, self.indication_cfg, self.fault_handler
        )
        self.src_entity_id = ByteFieldU16(1)
        self.src_pdu_conf = PduConfig(
            source_entity_id=self.src_entity_id,
            dest_entity_id=self.entity_id,
            transaction_seq_num=ByteFieldU8(1),
            trans_mode=TransmissionMode.UNACKNOWLEDGED,
        )
        self.transaction_id = TransactionId(self.src_entity_id, ByteFieldU8(1))
        self.closure_requested = False
        self.cfdp_user = CfdpUser()
        self.file_segment_len = 128
        self.cfdp_user.eof_recv_indication = MagicMock()
        self.cfdp_user.file_segment_recv_indication = MagicMock()
        self.cfdp_user.transaction_finished_indication = MagicMock()
        self.src_file_path = Path(f"{tempfile.gettempdir()}/hello.txt")
        if self.src_file_path.exists():
            os.remove(self.src_file_path)
        self.dest_file_path = Path(f"{tempfile.gettempdir()}/hello_dest.txt")
        if self.dest_file_path.exists():
            os.remove(self.dest_file_path)
        self.remote_cfg_table = RemoteEntityCfgTable()
        self.remote_cfg = RemoteEntityCfg(
            entity_id=self.src_entity_id,
            check_limit=2,
            crc_type=ChecksumType.CRC_32,
            closure_requested=False,
            crc_on_transmission=False,
            default_transmission_mode=TransmissionMode.UNACKNOWLEDGED,
            max_file_segment_len=self.file_segment_len,
            max_packet_len=self.file_segment_len,
        )
        self.remote_cfg_table.add_config(self.remote_cfg)
        self.timeout_check_limit_handling_ms = 10
        self.dest_handler = DestHandler(
            self.local_cfg,
            self.cfdp_user,
            self.remote_cfg_table,
            TestCheckTimerProvider(
                timeout_dest_entity_ms=self.timeout_check_limit_handling_ms
            ),
        )

    def test_remote_cfg_does_not_exist(self):
        # Re-create empty table
        self.remote_cfg_table = RemoteEntityCfgTable()
        self.dest_handler = DestHandler(
            self.local_cfg,
            self.cfdp_user,
            self.remote_cfg_table,
            TestCheckTimerProvider(5),
        )
        metadata_params = MetadataParams(
            checksum_type=ChecksumType.NULL_CHECKSUM,
            closure_requested=False,
            source_file_name=self.src_file_path.as_posix(),
            dest_file_name=self.dest_file_path.as_posix(),
            file_size=0,
        )
        file_transfer_init = MetadataPdu(
            params=metadata_params, pdu_conf=self.src_pdu_conf
        )
        self._state_checker(None, False, CfdpState.IDLE, TransactionStep.IDLE)
        with self.assertRaises(NoRemoteEntityCfgFound):
            self.dest_handler.insert_packet(file_transfer_init)

    def _generic_empty_file_transfer_init(self):
        metadata_params = MetadataParams(
            checksum_type=ChecksumType.NULL_CHECKSUM,
            closure_requested=self.closure_requested,
            source_file_name=self.src_file_path.as_posix(),
            dest_file_name=self.dest_file_path.as_posix(),
            file_size=0,
        )
        file_transfer_init = MetadataPdu(
            params=metadata_params, pdu_conf=self.src_pdu_conf
        )
        self._state_checker(None, False, CfdpState.IDLE, TransactionStep.IDLE)
        self.dest_handler.insert_packet(file_transfer_init)
        fsm_res = self.dest_handler.state_machine()
        self.assertFalse(fsm_res.states.packets_ready)

    def test_empty_file_reception(self):
        self._generic_empty_file_transfer_init()
        self.assertEqual(
            self.dest_handler.states.step, TransactionStep.RECEIVING_FILE_DATA
        )
        eof_pdu = EofPdu(
            file_size=0, file_checksum=NULL_CHECKSUM_U32, pdu_conf=self.src_pdu_conf
        )
        self.dest_handler.insert_packet(eof_pdu)
        fsm_res = self.dest_handler.state_machine()
        self._state_checker(fsm_res, False, CfdpState.IDLE, TransactionStep.IDLE)
        self._check_eof_recv_indication(fsm_res)
        self._check_finished_recv_indication_success(fsm_res)
        self.assertTrue(self.dest_file_path.exists())
        self.assertEqual(self.dest_file_path.stat().st_size, 0)

    def _assert_generic_no_error_finished_pdu(self, fsm_res: FsmResult):
        self.assertTrue(fsm_res.states.packets_ready)
        next_pdu = self.dest_handler.get_next_packet()
        assert next_pdu is not None
        self.assertEqual(next_pdu.pdu_type, PduType.FILE_DIRECTIVE)
        self.assertEqual(next_pdu.pdu_directive_type, DirectiveType.FINISHED_PDU)

        finished_pdu = next_pdu.to_finished_pdu()
        self.assertEqual(finished_pdu.condition_code, ConditionCode.NO_ERROR)
        self.assertEqual(finished_pdu.delivery_status, FileDeliveryStatus.FILE_RETAINED)
        self.assertEqual(finished_pdu.delivery_code, DeliveryCode.DATA_COMPLETE)
        self.assertEqual(finished_pdu.direction, Direction.TOWARDS_SENDER)
        self.assertIsNone(finished_pdu.fault_location)
        self.assertEqual(len(finished_pdu.file_store_responses), 0)

    def test_empty_file_reception_with_closure(self):
        self.closure_requested = True
        self._generic_empty_file_transfer_init()
        self.assertEqual(
            self.dest_handler.states.step, TransactionStep.RECEIVING_FILE_DATA
        )
        eof_pdu = EofPdu(
            file_size=0, file_checksum=NULL_CHECKSUM_U32, pdu_conf=self.src_pdu_conf
        )
        self.dest_handler.insert_packet(eof_pdu)
        fsm_res = self.dest_handler.state_machine()
        self._state_checker(
            fsm_res,
            True,
            CfdpState.BUSY_CLASS_1_NACKED,
            TransactionStep.SENDING_FINISHED_PDU,
        )
        self._check_eof_recv_indication(fsm_res)
        self._check_finished_recv_indication_success(fsm_res)
        self.assertTrue(self.dest_file_path.exists())
        self.assertEqual(self.dest_file_path.stat().st_size, 0)
        self._assert_generic_no_error_finished_pdu(fsm_res)

    def test_small_file_reception(self):
        data = "Hello World\n".encode()
        with open(self.src_file_path, "wb") as of:
            of.write(data)
        crc32_func = mkPredefinedCrcFun("crc32")
        crc32 = struct.pack("!I", crc32_func(data))
        file_size = self.src_file_path.stat().st_size
        self._source_simulator_transfer_init_with_metadata(
            checksum=ChecksumType.CRC_32,
            file_size=file_size,
            file_path=self.src_file_path.as_posix(),
        )
        with open(self.src_file_path, "rb") as rf:
            read_data = rf.read()
        fd_params = FileDataParams(file_data=read_data, offset=0)
        file_data_pdu = FileDataPdu(params=fd_params, pdu_conf=self.src_pdu_conf)
        self.dest_handler.insert_packet(file_data_pdu)
        fsm_res = self.dest_handler.state_machine()
        self._state_checker(
            fsm_res,
            False,
            CfdpState.BUSY_CLASS_1_NACKED,
            TransactionStep.RECEIVING_FILE_DATA,
        )
        eof_pdu = EofPdu(
            file_size=file_size,
            file_checksum=crc32,
            pdu_conf=self.src_pdu_conf,
        )
        self.dest_handler.insert_packet(eof_pdu)
        fsm_res = self.dest_handler.state_machine()
        self._state_checker(fsm_res, False, CfdpState.IDLE, TransactionStep.IDLE)
        self._check_eof_recv_indication(fsm_res)
        self._check_finished_recv_indication_success(fsm_res)

    def test_small_file_reception_with_closure(self):
        self.closure_requested = True
        data = "Hello World\n".encode()
        with open(self.src_file_path, "wb") as of:
            of.write(data)
        crc32_func = mkPredefinedCrcFun("crc32")
        crc32 = struct.pack("!I", crc32_func(data))
        file_size = self.src_file_path.stat().st_size
        self._source_simulator_transfer_init_with_metadata(
            checksum=ChecksumType.CRC_32,
            file_size=file_size,
            file_path=self.src_file_path.as_posix(),
        )
        with open(self.src_file_path, "rb") as rf:
            read_data = rf.read()
        fd_params = FileDataParams(file_data=read_data, offset=0)
        file_data_pdu = FileDataPdu(params=fd_params, pdu_conf=self.src_pdu_conf)
        self.dest_handler.insert_packet(file_data_pdu)
        fsm_res = self.dest_handler.state_machine()
        self._state_checker(
            fsm_res,
            False,
            CfdpState.BUSY_CLASS_1_NACKED,
            TransactionStep.RECEIVING_FILE_DATA,
        )
        eof_pdu = EofPdu(
            file_size=file_size,
            file_checksum=crc32,
            pdu_conf=self.src_pdu_conf,
        )
        self.dest_handler.insert_packet(eof_pdu)
        fsm_res = self.dest_handler.state_machine()
        self._state_checker(
            fsm_res,
            True,
            CfdpState.BUSY_CLASS_1_NACKED,
            TransactionStep.SENDING_FINISHED_PDU,
        )
        self._check_eof_recv_indication(fsm_res)
        self._check_finished_recv_indication_success(fsm_res)
        self._assert_generic_no_error_finished_pdu(fsm_res)
        fsm_res = self.dest_handler.state_machine()
        self._state_checker(
            fsm_res,
            False,
            CfdpState.IDLE,
            TransactionStep.IDLE,
        )

    def test_larger_file_reception(self):
        # This tests generates two file data PDUs, but the second one does not have a
        # full segment length
        file_info = self.random_data_two_file_segments()
        self._state_checker(None, False, CfdpState.IDLE, TransactionStep.IDLE)
        self._source_simulator_transfer_init_with_metadata(
            checksum=ChecksumType.CRC_32,
            file_size=file_info.file_size,
            file_path=self.src_file_path.as_posix(),
        )
        fsm_res = self.pass_file_segment(
            file_info.rand_data[0 : self.file_segment_len], 0
        )
        self._state_checker(
            fsm_res,
            False,
            CfdpState.BUSY_CLASS_1_NACKED,
            TransactionStep.RECEIVING_FILE_DATA,
        )
        self.cfdp_user.file_segment_recv_indication.assert_called()
        self.assertEqual(self.cfdp_user.file_segment_recv_indication.call_count, 1)
        seg_recv_params = cast(
            FileSegmentRecvdParams,
            self.cfdp_user.file_segment_recv_indication.call_args.args[0],
        )
        self.assertEqual(seg_recv_params.transaction_id, self.transaction_id)
        fd_params = FileDataParams(
            file_data=file_info.rand_data[self.file_segment_len :],
            offset=self.file_segment_len,
        )
        file_data_pdu = FileDataPdu(params=fd_params, pdu_conf=self.src_pdu_conf)
        self.dest_handler.insert_packet(file_data_pdu)
        fsm_res = self.dest_handler.state_machine()
        self._state_checker(
            fsm_res,
            False,
            CfdpState.BUSY_CLASS_1_NACKED,
            TransactionStep.RECEIVING_FILE_DATA,
        )
        eof_pdu = EofPdu(
            file_size=file_info.file_size,
            file_checksum=file_info.crc32,
            pdu_conf=self.src_pdu_conf,
        )
        self.dest_handler.insert_packet(eof_pdu)
        fsm_res = self.dest_handler.state_machine()
        self._state_checker(fsm_res, False, CfdpState.IDLE, TransactionStep.IDLE)
        self._check_eof_recv_indication(fsm_res)
        self._check_finished_recv_indication_success(fsm_res)

    def _generic_check_limit_test(self, file_data: bytes):
        with open(self.src_file_path, "wb") as of:
            of.write(file_data)
        crc32_func = mkPredefinedCrcFun("crc32")
        crc32 = struct.pack("!I", crc32_func(file_data))
        file_size = self.src_file_path.stat().st_size
        self._source_simulator_transfer_init_with_metadata(
            checksum=ChecksumType.CRC_32,
            file_size=file_size,
            file_path=self.src_file_path.as_posix(),
        )
        eof_pdu = EofPdu(
            file_size=file_size,
            file_checksum=crc32,
            pdu_conf=self.src_pdu_conf,
        )
        self.dest_handler.insert_packet(eof_pdu)
        fsm_res = self.dest_handler.state_machine()
        self._state_checker(
            fsm_res,
            False,
            CfdpState.BUSY_CLASS_1_NACKED,
            TransactionStep.RECV_FILE_DATA_WITH_CHECK_LIMIT_HANDLING,
        )
        self._check_eof_recv_indication(fsm_res)

    def test_check_timer_mechanism(self):
        data = "Hello World\n".encode()
        self._generic_check_limit_test(data)
        fd_params = FileDataParams(
            file_data=data,
            offset=0,
        )
        file_data_pdu = FileDataPdu(params=fd_params, pdu_conf=self.src_pdu_conf)
        self.dest_handler.insert_packet(file_data_pdu)
        fsm_res = self.dest_handler.state_machine()
        self._state_checker(
            fsm_res,
            False,
            CfdpState.BUSY_CLASS_1_NACKED,
            TransactionStep.RECV_FILE_DATA_WITH_CHECK_LIMIT_HANDLING,
        )
        self.assertFalse(self.dest_handler.packets_ready)
        time.sleep(0.015)
        fsm_res = self.dest_handler.state_machine()
        self._state_checker(
            fsm_res,
            False,
            CfdpState.IDLE,
            TransactionStep.IDLE,
        )

    def test_check_limit_reached(self):
        data = "Hello World\n".encode()
        self._generic_check_limit_test(data)
        # Check counter should be incremented by one.
        time.sleep(0.015)
        fsm_res = self.dest_handler.state_machine()
        self._state_checker(
            fsm_res,
            False,
            CfdpState.BUSY_CLASS_1_NACKED,
            TransactionStep.RECV_FILE_DATA_WITH_CHECK_LIMIT_HANDLING,
        )
        self.assertEqual(self.dest_handler.current_check_counter, 1)
        # Check counter reaches 2, check limit fault should be declared
        time.sleep(0.015)
        fsm_res = self.dest_handler.state_machine()
        self.assertEqual(self.dest_handler.current_check_counter, 0)
        self._state_checker(
            fsm_res,
            False,
            CfdpState.IDLE,
            TransactionStep.IDLE,
        )

    def random_data_two_file_segments(self):
        if sys.version_info >= (3, 9):
            rand_data = random.randbytes(round(self.file_segment_len * 1.3))
        else:
            rand_data = os.urandom(round(self.file_segment_len * 1.3))
        file_size = len(rand_data)
        crc32_func = mkPredefinedCrcFun("crc32")
        crc32 = struct.pack("!I", crc32_func(rand_data))
        return FileInfo(file_size=file_size, crc32=crc32, rand_data=rand_data)

    def test_file_is_overwritten(self):
        with open(self.dest_file_path, "w") as of:
            of.write("This file will be truncated")
        self.test_small_file_reception()

    def test_file_data_pdu_before_metadata_is_discarded(self):
        file_info = self.random_data_two_file_segments()
        with self.assertRaises(PduIgnoredForDest):
            # Pass file data PDU first. Will be discarded
            fsm_res = self.pass_file_segment(
                file_info.rand_data[0 : self.file_segment_len], 0
            )
            self._state_checker(fsm_res, False, CfdpState.IDLE, TransactionStep.IDLE)
        self._source_simulator_transfer_init_with_metadata(
            checksum=ChecksumType.CRC_32,
            file_size=file_info.file_size,
            file_path=self.src_file_path.as_posix(),
        )
        fsm_res = self.pass_file_segment(
            segment=file_info.rand_data[: self.file_segment_len],
            offset=self.file_segment_len,
        )
        fsm_res = self.pass_file_segment(
            segment=file_info.rand_data[self.file_segment_len :],
            offset=self.file_segment_len,
        )
        self._state_checker(
            fsm_res,
            False,
            CfdpState.BUSY_CLASS_1_NACKED,
            TransactionStep.RECEIVING_FILE_DATA,
        )
        eof_pdu = EofPdu(
            file_size=file_info.file_size,
            file_checksum=file_info.crc32,
            pdu_conf=self.src_pdu_conf,
        )
        self.dest_handler.insert_packet(eof_pdu)
        fsm_res = self.dest_handler.state_machine()
        self.cfdp_user.transaction_finished_indication.assert_called_once()
        finished_args = cast(
            TransactionFinishedParams,
            self.cfdp_user.transaction_finished_indication.call_args.args[0],
        )
        # At least one segment was stored
        self.assertEqual(
            finished_args.finished_params.delivery_status,
            FileDeliveryStatus.FILE_RETAINED,
        )
        self.assertEqual(
            finished_args.finished_params.condition_code,
            ConditionCode.FILE_CHECKSUM_FAILURE,
        )
        self._state_checker(fsm_res, False, CfdpState.IDLE, TransactionStep.IDLE)

    def test_permission_error(self):
        with open(self.src_file_path, "w") as of:
            of.write("Hello World\n")
        self.src_file_path.chmod(0o444)
        # TODO: This will cause permission errors, but the error handling for this has not been
        #       implemented properly
        """
        file_size = src_file.stat().st_size
        self._source_simulator_transfer_init_with_metadata(
            checksum=ChecksumTypes.CRC_32,
            file_size=file_size,
            file_path=src_file.as_posix(),
        )
        with open(src_file, "rb") as rf:
            read_data = rf.read()
        fd_params = FileDataParams(file_data=read_data, offset=0)
        file_data_pdu = FileDataPdu(params=fd_params, pdu_conf=self.src_pdu_conf)
        self.dest_handler.pass_packet(file_data_pdu)
        fsm_res = self.dest_handler.state_machine()
        self._state_checker(
            fsm_res, CfdpStates.BUSY_CLASS_1_NACKED, TransactionStep.RECEIVING_FILE_DATA
        )
        """
        self.src_file_path.chmod(0o777)

    def _check_eof_recv_indication(self, fsm_res: FsmResult):
        self.cfdp_user.eof_recv_indication.assert_called_once()
        self.assertEqual(
            self.cfdp_user.eof_recv_indication.call_args.args[0], self.transaction_id
        )
        self.assertEqual(fsm_res.states.transaction_id, self.transaction_id)

    def _check_finished_recv_indication_success(self, fsm_res: FsmResult):
        finished_params = cast(
            TransactionFinishedParams,
            self.cfdp_user.transaction_finished_indication.call_args.args[0],
        )
        self.assertEqual(finished_params.transaction_id, self.transaction_id)
        self.assertEqual(fsm_res.states.transaction_id, self.transaction_id)
        self.assertEqual(
            finished_params.finished_params.condition_code, ConditionCode.NO_ERROR
        )

    def pass_file_segment(self, segment: bytes, offset) -> FsmResult:
        fd_params = FileDataParams(file_data=segment, offset=offset)
        file_data_pdu = FileDataPdu(params=fd_params, pdu_conf=self.src_pdu_conf)
        self.dest_handler.insert_packet(file_data_pdu)
        return self.dest_handler.state_machine()

    def _state_checker(
        self,
        fsm_res: Optional[FsmResult],
        packets_ready: bool,
        expected_state: CfdpState,
        expected_transaction: TransactionStep,
    ):
        if fsm_res is not None:
            self.assertEqual(fsm_res.states.state, expected_state)
            self.assertEqual(fsm_res.states.step, expected_transaction)
            self.assertEqual(fsm_res.states.packets_ready, packets_ready)
        self.assertEqual(self.dest_handler.states.state, expected_state)
        self.assertEqual(self.dest_handler.states.step, expected_transaction)
        self.assertEqual(self.dest_handler.packets_ready, packets_ready)

    def _source_simulator_transfer_init_with_metadata(
        self, checksum: ChecksumType, file_path: str, file_size: int
    ):
        """A file transfer on the receiving side is always initiated by sending a metadata PDU.
        This function simulates a CFDP source entity which initiates a file transfer by sending
        this PDU.
        """
        metadata_params = MetadataParams(
            checksum_type=checksum,
            closure_requested=self.closure_requested,
            source_file_name=file_path,
            dest_file_name=self.dest_file_path.as_posix(),
            file_size=file_size,
        )
        file_transfer_init = MetadataPdu(
            params=metadata_params, pdu_conf=self.src_pdu_conf
        )
        self._state_checker(None, False, CfdpState.IDLE, TransactionStep.IDLE)
        self.dest_handler.insert_packet(file_transfer_init)
        fsm_res = self.dest_handler.state_machine()
        self._state_checker(
            fsm_res,
            False,
            CfdpState.BUSY_CLASS_1_NACKED,
            TransactionStep.RECEIVING_FILE_DATA,
        )

    def tearDown(self) -> None:
        # self.dest_handler.finish()
        if self.dest_file_path.exists():
            os.remove(self.dest_file_path)
        if self.src_file_path.exists():
            os.remove(self.src_file_path)
