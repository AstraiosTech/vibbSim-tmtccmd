from pathlib import Path
from typing import Optional, List, cast

from spacepackets.cfdp import (
    SegmentationControl,
    TransmissionMode,
    FaultHandlerOverrideTlv,
    FlowLabelTlv,
    MessageToUserTlv,
    FileStoreRequestTlv,
)
from spacepackets.util import UnsignedByteField
from tmtccmd.cfdp.defs import CfdpRequestType
import dataclasses

from tmtccmd.config.defs import CfdpParams


class CfdpRequestBase:
    def __init__(self, req_type: CfdpRequestType):
        self.req_type = req_type


@dataclasses.dataclass
class PutRequest:
    destination_id: UnsignedByteField
    # All the following fields are optional because a put request can also be a metadata-only
    # request
    source_file: Optional[Path]
    dest_file: Optional[str]
    trans_mode: Optional[TransmissionMode]
    closure_requested: Optional[bool]
    seg_ctrl: Optional[
        SegmentationControl
    ] = SegmentationControl.NO_RECORD_BOUNDARIES_PRESERVATION
    fault_handler_overrides: Optional[List[FaultHandlerOverrideTlv]] = None
    flow_label_tlv: Optional[FlowLabelTlv] = None
    msgs_to_user: Optional[List[MessageToUserTlv]] = None
    fs_requests: Optional[List[FileStoreRequestTlv]] = None

    @property
    def metadata_only(self):
        if self.source_file is None and self.dest_file is None:
            return True
        return False

    def __str__(self):
        src_file_str = "Unknown source file"
        dest_file_str = "Unknown destination file"
        if not self.metadata_only:
            src_file_str = f"Source File: {self.source_file}"
            dest_file_str = f"Destination File: {self.dest_file}"
        if self.trans_mode:
            if self.trans_mode == TransmissionMode.ACKNOWLEDGED:
                trans_mode_str = "Transmission Mode: Class 2 Acknowledged"
            else:
                trans_mode_str = "Transmission Mode: Class 1 Unacknowledged"
        else:
            trans_mode_str = "Transmission Mode from MIB"
        if self.closure_requested is not None:
            if self.closure_requested:
                closure_str = "Closure requested"
            else:
                closure_str = "No closure requested"
        else:
            closure_str = "Closure information from MIB"
        if not self.metadata_only:
            print_str = (
                f"Destination ID: {self.destination_id}\n"
                f"{src_file_str}\n{dest_file_str}\n{trans_mode_str}\n{closure_str}"
            )
        else:
            # TODO: Print out other parameters
            print_str = f"Destination ID: {self.destination_id}"
        return print_str


class PutRequestCfgWrapper(CfdpRequestBase):
    def __init__(self, cfg: CfdpParams):
        super().__init__(CfdpRequestType.PUT)
        self.cfg = cfg

    def __repr__(self):
        return f"{self.__class__.__name__}(cfg={self.cfg})"


class CfdpRequestWrapper:
    def __init__(self, base: Optional[CfdpRequestBase]):
        self.base = base

    @property
    def request_type(self) -> CfdpRequestType:
        return self.base.req_type

    @property
    def request(self) -> CfdpRequestType:
        return self.base.req_type

    def to_put_request(self) -> PutRequestCfgWrapper:
        if self.base.req_type != CfdpRequestType.PUT:
            raise TypeError(
                f"Request is not a {PutRequestCfgWrapper.__name__}: {self.base!r}"
            )
        return cast(PutRequestCfgWrapper, self.base)
