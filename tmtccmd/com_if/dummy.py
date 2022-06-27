"""Dummy Virtual Communication Interface. Currently serves to use the TMTC program without needing
external hardware or an extra socket
"""
from typing import Optional

from spacepackets.ecss.pus_1_verification import RequestId
from spacepackets.ecss.tc import PusTelecommand

from tmtccmd.com_if import ComInterface
from tmtccmd.config import CoreComInterfaces
from tmtccmd.tm import TelemetryListT
from tmtccmd.tm.pus_1_verification import Service1TmExtended
from tmtccmd.tm.pus_17_test import Subservices, Service17TmExtended
from tmtccmd.logging import get_console_logger


LOGGER = get_console_logger()


class DummyHandler:
    def __init__(self):
        self.last_tc: Optional[PusTelecommand] = None
        self.next_telemetry_package = []
        self.current_ssc = 0
        self.reply_pending = False

    def pass_telecommand(self, data: bytearray):
        self.last_tc = PusTelecommand.unpack(data)
        self.reply_pending = True
        self.generate_reply_package()

    def generate_reply_package(self):
        """Generate a reply package. Currently, this only generates a reply for a ping telecommand."""
        if self.last_tc.service == 17:
            if self.last_tc.subservice == 1:
                tm_packer = Service1TmExtended(
                    subservice=1,
                    ssc=self.current_ssc,
                    tc_request_id=RequestId(
                        self.last_tc.packet_id, self.last_tc.packet_seq_ctrl
                    ),
                )

                self.current_ssc += 1
                tm_packet_raw = tm_packer.pack()
                self.next_telemetry_package.append(tm_packet_raw)
                tm_packer = Service1TmExtended(
                    subservice=7,
                    ssc=self.current_ssc,
                    tc_request_id=RequestId(
                        self.last_tc.packet_id, self.last_tc.packet_seq_ctrl
                    ),
                )
                tm_packet_raw = tm_packer.pack()
                self.next_telemetry_package.append(tm_packet_raw)
                self.current_ssc += 1

                tm_packer = Service17TmExtended(subservice=Subservices.TM_REPLY)
                tm_packet_raw = tm_packer.pack()
                self.next_telemetry_package.append(tm_packet_raw)
                self.current_ssc += 1

    def receive_reply_package(self) -> TelemetryListT:
        if self.reply_pending:
            return_list = self.next_telemetry_package.copy()
            self.next_telemetry_package.clear()
            self.reply_pending = False
            return return_list
        else:
            return []


class DummyComIF(ComInterface):
    def __init__(self):
        super().__init__(com_if_id=CoreComInterfaces.DUMMY.value)
        self.dummy_handler = DummyHandler()
        self._open = False
        self.initialized = False

    def initialize(self, args: any = None) -> any:
        self.initialized = True

    def open(self, args: any = None) -> None:
        self._open = True

    def is_open(self) -> bool:
        return self._open

    def close(self, args: any = None) -> None:
        self._open = False

    def data_available(self, timeout: float = 0, parameters: any = 0):
        if self.dummy_handler.reply_pending:
            return True
        return False

    def receive(self, parameters: any = 0) -> TelemetryListT:
        return self.dummy_handler.receive_reply_package()

    def send(self, data: bytearray):
        if data is not None:
            self.dummy_handler.pass_telecommand(data)
