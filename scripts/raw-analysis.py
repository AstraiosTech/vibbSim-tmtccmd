#!/usr/bin/env python3
from base64 import b64decode
from spacepackets.ccsds.time import CdsShortTimestamp
from spacepackets.ecss.tm import PusTelemetry
from spacepackets.ecss.pus_1_verification import Service1Tm, UnpackParams

bruh = "CGX6cQAdIAEIOzcAAEBedwUTOzkYZe5WAAEAAAAAAAAAAF4z"
data = b64decode(bruh)
tm = PusTelemetry.unpack(data, CdsShortTimestamp.empty())
srv1_tm = Service1Tm.from_tm(
    tm, UnpackParams(time_reader=CdsShortTimestamp.empty(), bytes_err_code=2)
)
print(f"service {tm.service} subservice {tm.subservice}")
print(f"error code: {srv1_tm.error_code}")
