from __future__ import annotations

import struct
from abc import abstractmethod
from typing import Deque, Optional

from spacepackets.ccsds.time import CdsShortTimestamp
from spacepackets.ecss.tm import PusVersion, PusTelemetry
from spacepackets.ecss.pus_1_verification import (
    Service1Tm,
    Subservices,
    VerificationParams,
    UnpackParams,
)

from tmtccmd.tm.base import PusTmInfoBase, PusTmBase
from tmtccmd.logging import get_console_logger

LOGGER = get_console_logger()


class Service1TmExtended(PusTmBase, PusTmInfoBase, Service1Tm):
    """Service 1 TM class representation. Can be used to deserialize raw service 1 packets."""

    def __init__(
        self,
        subservice: Subservices,
        verif_params: Optional[VerificationParams] = None,
        time: CdsShortTimestamp = None,
        seq_count: int = 0,
        apid: int = -1,
        packet_version: int = 0b000,
        pus_version: PusVersion = PusVersion.GLOBAL_CONFIG,
        secondary_header_flag: bool = True,
        space_time_ref: int = 0b0000,
        destination_id: int = 0,
    ):
        Service1Tm.__init__(
            self,
            verif_params=verif_params,
            subservice=subservice,
            time=time,
            seq_count=seq_count,
            apid=apid,
            packet_version=packet_version,
            pus_version=pus_version,
            secondary_header_flag=secondary_header_flag,
            space_time_ref=space_time_ref,
            destination_id=destination_id,
        )
        PusTmBase.__init__(self, pus_tm=self.pus_tm)
        PusTmInfoBase.__init__(self, pus_tm=self.pus_tm)
        self._error_param_1 = 0
        self._error_param_2 = 0

    @classmethod
    def __empty(cls) -> Service1TmExtended:
        return cls(subservice=Subservices.INVALID)

    @classmethod
    def unpack(cls, data: bytes, params: UnpackParams) -> Service1TmExtended:
        """Parse a service 1 telemetry packet

        :param params:
        :param data:
        :raises ValueError: Raw telemetry too short
        :return:
        """
        service_1_tm = cls.__empty()
        service_1_tm.pus_tm = PusTelemetry.unpack(raw_telemetry=data)
        cls._unpack_raw_tm(service_1_tm, params)
        # FSFW specific
        if service_1_tm.has_failure_notice:
            service_1_tm._error_param_1 = struct.unpack(
                "!I", service_1_tm.failure_notice.data[1:5]
            )
            service_1_tm._error_param_1 = struct.unpack(
                "!I", service_1_tm.failure_notice.data[6:10]
            )
        return service_1_tm

    @abstractmethod
    def append_telemetry_content(self, content_list: list):
        super().append_telemetry_content(content_list=content_list)
        content_list.append(self.tc_req_id.tc_packet_id)
        content_list.append(self.tc_req_id.tc_psc)
        if self.has_failure_notice:
            if self.is_step_reply:
                content_list.append(str(self.step_id))
            content_list.append(str(hex(self.error_code.val)))
            content_list.append(
                f"hex {self.failure_notice:04x} dec {self.failure_notice}"
            )
            content_list.append(
                f"hex {self.failure_notice.data[0:4]:04x} dec {self._error_param_2}"
            )
        elif self.is_step_reply:
            content_list.append(str(self.step_id))

    @abstractmethod
    def append_telemetry_column_headers(self, header_list: list):
        super().append_telemetry_column_headers(header_list=header_list)
        header_list.append("TC Packet ID")
        header_list.append("TC PSC")
        if self.has_failure_notice:
            if self.is_step_reply:
                header_list.append("Step Number")
            header_list.append("Return Value")
            header_list.append("Error Param 1")
            header_list.append("Error Param 2")
        elif self.is_step_reply:
            header_list.append("Step Number")

    def _unpack_failure_verification(self, params: UnpackParams):
        """Handle parsing a verification failure packet, subservice ID 2, 4, 6 or 8"""
        super()._unpack_failure_verification(params)
        self.set_packet_info("Failure Verficiation")
        subservice = self.pus_tm.subservice
        if subservice == Subservices.TM_ACCEPTANCE_FAILURE:
            self.append_packet_info(" : Acceptance failure")
        elif subservice == Subservices.TM_START_FAILURE:
            self.append_packet_info(" : Start failure")
        elif subservice == Subservices.TM_STEP_FAILURE:
            self.append_packet_info(" : Step Failure")
        elif subservice == Subservices.TM_COMPLETION_FAILURE:
            self.append_packet_info(" : Completion Failure")

    def _unpack_success_verification(self, params: UnpackParams):
        super()._unpack_success_verification(params)
        self.set_packet_info("Success Verification")
        if self.subservice == Subservices.TM_ACCEPTANCE_SUCCESS:
            self.append_packet_info(" : Acceptance success")
        elif self.subservice == Subservices.TM_START_SUCCESS:
            self.append_packet_info(" : Start success")
        elif self.subservice == Subservices.TM_STEP_SUCCESS:
            self.append_packet_info(" : Step Success")
        elif self.subservice == Subservices.TM_COMPLETION_SUCCESS:
            self.append_packet_info(" : Completion success")


PusVerifQueue = Deque[Service1Tm]
