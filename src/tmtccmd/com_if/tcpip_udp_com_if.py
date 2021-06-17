"""
:file:      tcpip_udp_com_if.py
:date:      13.05.2021
:brief:     UDP Communication Interface
:author:    R. Mueller
"""
import select
import socket
from typing import Union

from tmtccmd.utility.logger import get_logger
from tmtccmd.config.definitions import CoreModeList
from tmtccmd.com_if.com_interface_base import CommunicationInterface
from tmtccmd.pus_tm.factory import PusTelemetryFactory, TelemetryListT
from tmtccmd.utility.tmtc_printer import TmTcPrinter
from tmtccmd.ecss.tc import PusTelecommand
from tmtccmd.config.definitions import EthernetAddressT

LOGGER = get_logger()

UDP_RECV_WIRETAPPING_ENABLED = False
UDP_SEND_WIRETAPPING_ENABLED = False


# pylint: disable=abstract-method
# pylint: disable=arguments-differ
# pylint: disable=too-many-arguments
class TcpIpUdpComIF(CommunicationInterface):
    """Communication interface for UDP communication."""
    def __init__(
            self, com_if_key: str, tm_timeout: float, tc_timeout_factor: float, send_address: EthernetAddressT,
            max_recv_size: int, recv_addr: Union[None, EthernetAddressT] = None,
            tmtc_printer: Union[None, TmTcPrinter] = None, init_mode: int = CoreModeList.LISTENER_MODE):
        """Initialize a communication interface to send and receive UDP datagrams.
        :param tm_timeout:
        :param tc_timeout_factor:
        :param send_address:
        :param max_recv_size:
        :param recv_addr:
        :param tmtc_printer:        Printer instance, can be passed optionally to allow packet debugging
        """
        super().__init__(com_if_key=com_if_key, tmtc_printer=tmtc_printer)
        self.tm_timeout = tm_timeout
        self.tc_timeout_factor = tc_timeout_factor
        self.udp_socket = None
        self.send_address = send_address
        self.recv_addr = recv_addr
        self.max_recv_size = max_recv_size
        self.init_mode = init_mode

    def __del__(self):
        try:
            self.close()
        except IOError:
            LOGGER.warning("Could not close UDP communication interface!")

    def initialize(self, args: any = None) -> any:
        pass

    def open(self, args: any = None):
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Bind is possible but should not be necessary, and introduces risk of port alread
        # being used.
        # See: https://docs.microsoft.com/en-us/windows/win32/api/winsock/nf-winsock-bind
        if self.recv_addr is not None:
            LOGGER.info(f"Binding UDP socket to {self.recv_addr[0]} and port {self.recv_addr[1]}")
            self.udp_socket.bind(self.recv_addr)
        # Set non-blocking because we use select.
        self.udp_socket.setblocking(False)
        if self.init_mode == CoreModeList.LISTENER_MODE:
            from tmtccmd.pus_tc.service_17_test import pack_service17_ping_command
            # Send ping command immediately so the reception address is known for UDP
            ping_cmd = pack_service17_ping_command(ssc=0)
            self.send_telecommand(ping_cmd.pack(), ping_cmd)

    def close(self, args: any = None) -> None:
        if self.udp_socket is not None:
            self.udp_socket.close()

    def send(self, data: bytearray):
        if self.udp_socket is None:
            return
        bytes_sent = self.udp_socket.sendto(data, self.send_address)
        if bytes_sent != len(data):
            LOGGER.warning("Not all bytes were sent!")

    def data_available(self, timeout: float = 0) -> bool:
        if self.udp_socket is None:
            return False
        ready = select.select([self.udp_socket], [], [], timeout)
        if ready[0]:
            return True
        return False

    def receive(self, poll_timeout: float = 0) -> TelemetryListT:
        if self.udp_socket is None:
            return []
        try:
            ready = self.data_available(poll_timeout)
            if ready:
                data, sender_addr = self.udp_socket.recvfrom(self.max_recv_size)
                packet_list = [bytearray(data)]
                return packet_list
            return []
        except ConnectionResetError:
            LOGGER.warning("Connection reset exception occured!")
            return []


