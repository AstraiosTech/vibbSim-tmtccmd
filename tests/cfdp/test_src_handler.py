import os
import tempfile
from pathlib import Path
from unittest import TestCase
from crcmod.predefined import PredefinedCrc

from spacepackets.cfdp import (
    TransmissionModes,
    NULL_CHECKSUM_U32,
    ConditionCode,
    ChecksumTypes,
)
from spacepackets.cfdp.pdu import DirectiveType, FileDataPdu
from spacepackets.util import ByteFieldU16, UnsignedByteField, ByteFieldU32
from tmtccmd.cfdp import LocalIndicationCfg, LocalEntityCfg, RemoteEntityCfg
from tmtccmd.cfdp.defs import CfdpStates, SourceTransactionStep
from tmtccmd.cfdp.handler import SourceHandler, FsmResult
from tmtccmd.cfdp.handler.defs import PacketSendNotConfirmed
from tmtccmd.cfdp.request import PutRequestCfg, PutRequest, CfdpRequestWrapper
from tmtccmd.util import SeqCountProvider
from .cfdp_fault_handler_mock import FaultHandler
from .cfdp_user_mock import CfdpUser


class TestCfdpSourceHandler(TestCase):
    def common_setup(self, closure_requested: bool):
        self.indication_cfg = LocalIndicationCfg(True, True, True, True, True, True)
        self.fault_handler = FaultHandler()
        self.local_cfg = LocalEntityCfg(
            ByteFieldU16(1), self.indication_cfg, self.fault_handler
        )
        self.cfdp_user = CfdpUser()
        self.seq_num_provider = SeqCountProvider(bit_width=8)
        self.source_id = ByteFieldU16(1)
        self.dest_id = ByteFieldU16(2)
        self.file_path = Path(f"{tempfile.gettempdir()}/hello.txt")
        with open(self.file_path, "w"):
            pass
        self.file_segment_len = 256
        self.remote_cfg = RemoteEntityCfg(
            remote_entity_id=self.dest_id,
            max_file_segment_len=self.file_segment_len,
            closure_requested=closure_requested,
            crc_on_transmission=False,
            default_transmission_mode=TransmissionModes.UNACKNOWLEDGED,
        )
        # Create an empty file and send it via CFDP
        self.source_handler = SourceHandler(
            self.local_cfg, self.seq_num_provider, self.cfdp_user
        )

    def _common_empty_file_test(self):
        dest_path = "/tmp/hello_copy.txt"
        dest_id = ByteFieldU16(2)
        put_req_cfg = PutRequestCfg(
            destination_id=dest_id,
            source_file=self.file_path,
            dest_file=dest_path,
            # Let the transmission mode be auto-determined by the remote MIB
            trans_mode=None,
            closure_requested=None,
        )
        self._start_source_transaction(dest_id, PutRequest(put_req_cfg))
        fsm_res = self.source_handler.state_machine()
        self.assertEqual(fsm_res.states.state, CfdpStates.BUSY_CLASS_1_NACKED)
        self.assertEqual(fsm_res.states.step, SourceTransactionStep.SENDING_EOF)
        self.assertTrue(fsm_res.pdu_holder.is_file_directive)
        self.assertEqual(fsm_res.pdu_holder.pdu_directive_type, DirectiveType.EOF_PDU)
        eof_pdu = fsm_res.pdu_holder.to_eof_pdu()
        self.assertEqual(eof_pdu.file_checksum, NULL_CHECKSUM_U32)
        self.assertEqual(eof_pdu.file_size, 0)
        self.assertEqual(eof_pdu.condition_code, ConditionCode.NO_ERROR)
        self.assertEqual(eof_pdu.fault_location, None)
        # This indication will be called if the EOF send was confirmed
        self.assertFalse(self.cfdp_user.eof_sent_indication_was_called)
        self.source_handler.confirm_packet_sent_advance_fsm()
        self.assertTrue(self.cfdp_user.eof_sent_indication_was_called)
        self.assertEqual(self.cfdp_user.eof_sent_indication_call_count, 1)
        fsm_res = self.source_handler.state_machine()
        self.assertTrue(self.cfdp_user.transaction_finished_was_called)
        self.assertEqual(self.cfdp_user.transaction_finished_call_count, 1)
        self.source_handler.confirm_packet_sent_advance_fsm()
        self.assertEqual(fsm_res.states.state, CfdpStates.IDLE)
        self.assertEqual(fsm_res.states.step, SourceTransactionStep.IDLE)

    def _common_small_file_test(self):
        dest_path = "/tmp/hello_copy.txt"
        self.source_id = ByteFieldU32(1)
        self.dest_id = ByteFieldU32(2)
        self.source_handler.source_id = self.source_id
        put_req_cfg = PutRequestCfg(
            destination_id=self.dest_id,
            source_file=self.file_path,
            dest_file=dest_path,
            # Let the transmission mode be auto-determined by the remote MIB
            trans_mode=None,
            closure_requested=False,
        )
        with open(self.file_path, "wb") as of:
            crc32 = PredefinedCrc("crc32")
            data = "Hello World\n".encode()
            crc32.update(data)
            crc32 = crc32.digest()
            of.write(data)
        file_size = self.file_path.stat().st_size
        self._start_source_transaction(self.dest_id, PutRequest(put_req_cfg))
        fsm_res = self.source_handler.state_machine()
        file_data_pdu = self._check_file_data(fsm_res)
        self.assertFalse(file_data_pdu.has_segment_metadata)
        self.assertEqual(file_data_pdu.file_data, "Hello World\n".encode())
        self.assertEqual(file_data_pdu.offset, 0)
        self.source_handler.confirm_packet_sent_advance_fsm()
        fsm_res = self.source_handler.state_machine()
        self.assertEqual(fsm_res.states.state, CfdpStates.BUSY_CLASS_1_NACKED)
        self.assertEqual(fsm_res.states.step, SourceTransactionStep.SENDING_EOF)
        self.assertEqual(fsm_res.pdu_holder.pdu_directive_type, DirectiveType.EOF_PDU)
        eof_pdu = fsm_res.pdu_holder.to_eof_pdu()
        self.assertEqual(crc32, eof_pdu.file_checksum)
        self.assertEqual(eof_pdu.file_size, file_size)
        self.assertEqual(eof_pdu.condition_code, ConditionCode.NO_ERROR)
        with self.assertRaises(PacketSendNotConfirmed):
            self.source_handler.state_machine()

    def _check_file_data(self, fsm_res: FsmResult) -> FileDataPdu:
        self.assertEqual(fsm_res.states.state, CfdpStates.BUSY_CLASS_1_NACKED)
        self.assertEqual(fsm_res.states.step, SourceTransactionStep.SENDING_FILE_DATA)
        self.assertFalse(fsm_res.pdu_holder.is_file_directive)
        return fsm_res.pdu_holder.to_file_data_pdu()

    def _start_source_transaction(
        self, dest_id: UnsignedByteField, put_request: PutRequest
    ):
        wrapper = CfdpRequestWrapper(put_request)
        self.source_handler.start_transaction(wrapper, self.remote_cfg)
        fsm_res = self.source_handler.state_machine()
        self.assertEqual(fsm_res.states.state, CfdpStates.BUSY_CLASS_1_NACKED)
        self.assertEqual(fsm_res.states.step, SourceTransactionStep.SENDING_METADATA)
        self.assertTrue(self.cfdp_user.transaction_inidcation_was_called)
        self.assertEqual(self.cfdp_user.transaction_inidcation_call_count, 1)
        self.assertTrue(fsm_res.pdu_holder.is_file_directive)
        self.assertEqual(
            fsm_res.pdu_holder.pdu_directive_type, DirectiveType.METADATA_PDU
        )
        metadata_pdu = fsm_res.pdu_holder.to_metadata_pdu()
        if put_request.cfg.closure_requested is not None:
            self.assertEqual(
                metadata_pdu.params.closure_requested, put_request.cfg.closure_requested
            )
        self.assertEqual(metadata_pdu.checksum_type, ChecksumTypes.CRC_32)
        self.assertEqual(metadata_pdu.source_file_name, self.file_path.as_posix())
        self.assertEqual(metadata_pdu.dest_file_name, put_request.cfg.dest_file)
        self.assertEqual(metadata_pdu.dest_entity_id, dest_id)
        self.source_handler.confirm_packet_sent_advance_fsm()

    def tearDown(self) -> None:
        if self.file_path.exists():
            os.remove(self.file_path)
