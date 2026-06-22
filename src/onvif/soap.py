"""
Minimal ONVIF SOAP helpers — XML parsing and response generation.
Only the operations that Hikvision NVRs actually call are implemented.
"""

from datetime import datetime, timezone
from xml.etree import ElementTree as ET

# SOAP namespaces used in parsing
_SOAP12_BODY = "{http://www.w3.org/2003/05/soap-envelope}Body"
_SOAP11_BODY = "{http://schemas.xmlsoap.org/soap/envelope/}Body"


def parse_action(xml_body: bytes) -> str:
    """Return the local name of the first element inside the SOAP Body."""
    try:
        root = ET.fromstring(xml_body)
    except ET.ParseError:
        return ""
    body = root.find(_SOAP12_BODY) or root.find(_SOAP11_BODY)
    if body is None or len(body) == 0:
        return ""
    tag = body[0].tag
    return tag.split("}", 1)[1] if "}" in tag else tag


def _envelope(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<SOAP-ENV:Envelope'
        ' xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope"'
        ' xmlns:tds="http://www.onvif.org/ver10/device/wsdl"'
        ' xmlns:trt="http://www.onvif.org/ver10/media/wsdl"'
        ' xmlns:tt="http://www.onvif.org/ver10/schema">'
        f"<SOAP-ENV:Body>{body}</SOAP-ENV:Body>"
        "</SOAP-ENV:Envelope>"
    )


# ---------------------------------------------------------------------------
# Device service responses
# ---------------------------------------------------------------------------

def get_system_date_and_time() -> str:
    now = datetime.now(timezone.utc)
    body = (
        "<tds:GetSystemDateAndTimeResponse>"
        "<tds:SystemDateAndTime>"
        "<tt:DateTimeType>NTP</tt:DateTimeType>"
        "<tt:DaylightSavings>false</tt:DaylightSavings>"
        "<tt:TimeZone><tt:TZ>UTC0</tt:TZ></tt:TimeZone>"
        "<tt:UTCDateTime>"
        f"<tt:Time><tt:Hour>{now.hour}</tt:Hour><tt:Minute>{now.minute}</tt:Minute><tt:Second>{now.second}</tt:Second></tt:Time>"
        f"<tt:Date><tt:Year>{now.year}</tt:Year><tt:Month>{now.month}</tt:Month><tt:Day>{now.day}</tt:Day></tt:Date>"
        "</tt:UTCDateTime>"
        "</tds:SystemDateAndTime>"
        "</tds:GetSystemDateAndTimeResponse>"
    )
    return _envelope(body)


def get_device_information(serial: str) -> str:
    body = (
        "<tds:GetDeviceInformationResponse>"
        "<tds:Manufacturer>MIPC</tds:Manufacturer>"
        "<tds:Model>IPCamera</tds:Model>"
        "<tds:FirmwareVersion>1.0.0</tds:FirmwareVersion>"
        f"<tds:SerialNumber>{serial}</tds:SerialNumber>"
        "<tds:HardwareId>1.0</tds:HardwareId>"
        "</tds:GetDeviceInformationResponse>"
    )
    return _envelope(body)


def get_capabilities(host_ip: str, onvif_port: int) -> str:
    base = f"http://{host_ip}:{onvif_port}"
    body = (
        "<tds:GetCapabilitiesResponse>"
        "<tds:Capabilities>"
        f"<tt:Device><tt:XAddr>{base}/onvif/device_service</tt:XAddr></tt:Device>"
        "<tt:Media>"
        f"<tt:XAddr>{base}/onvif/media_service</tt:XAddr>"
        "<tt:StreamingCapabilities>"
        "<tt:RTPMulticast>false</tt:RTPMulticast>"
        "<tt:RTP_TCP>true</tt:RTP_TCP>"
        "<tt:RTP_RTSP_TCP>true</tt:RTP_RTSP_TCP>"
        "</tt:StreamingCapabilities>"
        "</tt:Media>"
        "</tds:Capabilities>"
        "</tds:GetCapabilitiesResponse>"
    )
    return _envelope(body)


def get_hostname(hostname: str) -> str:
    body = (
        "<tds:GetHostnameResponse>"
        f"<tds:HostnameInformation><tt:Name>{hostname}</tt:Name></tds:HostnameInformation>"
        "</tds:GetHostnameResponse>"
    )
    return _envelope(body)


def get_services(host_ip: str, onvif_port: int) -> str:
    base = f"http://{host_ip}:{onvif_port}"
    body = (
        "<tds:GetServicesResponse>"
        "<tds:Service>"
        "<tds:Namespace>http://www.onvif.org/ver10/device/wsdl</tds:Namespace>"
        f"<tds:XAddr>{base}/onvif/device_service</tds:XAddr>"
        "<tds:Version><tt:Major>2</tt:Major><tt:Minor>60</tt:Minor></tds:Version>"
        "</tds:Service>"
        "<tds:Service>"
        "<tds:Namespace>http://www.onvif.org/ver10/media/wsdl</tds:Namespace>"
        f"<tds:XAddr>{base}/onvif/media_service</tds:XAddr>"
        "<tds:Version><tt:Major>2</tt:Major><tt:Minor>60</tt:Minor></tds:Version>"
        "</tds:Service>"
        "</tds:GetServicesResponse>"
    )
    return _envelope(body)


def get_scopes() -> str:
    body = (
        "<tds:GetScopesResponse>"
        "<tds:Scopes><tt:ScopeDef>Fixed</tt:ScopeDef>"
        "<tt:ScopeItem>onvif://www.onvif.org/type/video_encoder</tt:ScopeItem></tds:Scopes>"
        "<tds:Scopes><tt:ScopeDef>Fixed</tt:ScopeDef>"
        "<tt:ScopeItem>onvif://www.onvif.org/Profile/Streaming</tt:ScopeItem></tds:Scopes>"
        "</tds:GetScopesResponse>"
    )
    return _envelope(body)


# ---------------------------------------------------------------------------
# Media service responses
# ---------------------------------------------------------------------------

def get_profiles(camera_name: str) -> str:
    body = (
        '<trt:GetProfilesResponse>'
        '<trt:Profiles token="MainStream" fixed="true">'
        '<tt:Name>MainStream</tt:Name>'
        '<tt:VideoSourceConfiguration token="VideoSource_0">'
        '<tt:Name>VideoSource</tt:Name>'
        '<tt:UseCount>1</tt:UseCount>'
        '<tt:SourceToken>VideoSource_0</tt:SourceToken>'
        '<tt:Bounds x="0" y="0" width="1920" height="1080"/>'
        '</tt:VideoSourceConfiguration>'
        '<tt:VideoEncoderConfiguration token="VideoEncoder_0">'
        '<tt:Name>VideoEncoder</tt:Name>'
        '<tt:UseCount>1</tt:UseCount>'
        '<tt:Encoding>H264</tt:Encoding>'
        '<tt:Resolution><tt:Width>1920</tt:Width><tt:Height>1080</tt:Height></tt:Resolution>'
        '<tt:Quality>4</tt:Quality>'
        '<tt:RateControl>'
        '<tt:FrameRateLimit>25</tt:FrameRateLimit>'
        '<tt:EncodingInterval>1</tt:EncodingInterval>'
        '<tt:BitrateLimit>4096</tt:BitrateLimit>'
        '</tt:RateControl>'
        '<tt:H264>'
        '<tt:GovLength>50</tt:GovLength>'
        '<tt:H264Profile>Main</tt:H264Profile>'
        '</tt:H264>'
        '<tt:Multicast>'
        '<tt:Address><tt:Type>IPv4</tt:Type><tt:IPv4Address>0.0.0.0</tt:IPv4Address></tt:Address>'
        '<tt:Port>0</tt:Port><tt:TTL>0</tt:TTL><tt:AutoStart>false</tt:AutoStart>'
        '</tt:Multicast>'
        '<tt:SessionTimeout>PT60S</tt:SessionTimeout>'
        '</tt:VideoEncoderConfiguration>'
        '</trt:Profiles>'
        '</trt:GetProfilesResponse>'
    )
    return _envelope(body)


def get_video_sources() -> str:
    body = (
        "<trt:GetVideoSourcesResponse>"
        '<trt:VideoSources token="VideoSource_0">'
        "<tt:Framerate>25</tt:Framerate>"
        "<tt:Resolution><tt:Width>1920</tt:Width><tt:Height>1080</tt:Height></tt:Resolution>"
        "</trt:VideoSources>"
        "</trt:GetVideoSourcesResponse>"
    )
    return _envelope(body)


def get_stream_uri(rtsp_url: str) -> str:
    body = (
        "<trt:GetStreamUriResponse>"
        "<trt:MediaUri>"
        f"<tt:Uri>{rtsp_url}</tt:Uri>"
        "<tt:InvalidAfterConnect>false</tt:InvalidAfterConnect>"
        "<tt:InvalidAfterReboot>false</tt:InvalidAfterReboot>"
        "<tt:Timeout>PT0S</tt:Timeout>"
        "</trt:MediaUri>"
        "</trt:GetStreamUriResponse>"
    )
    return _envelope(body)


def get_snapshot_uri(snapshot_url: str) -> str:
    body = (
        "<trt:GetSnapshotUriResponse>"
        "<trt:MediaUri>"
        f"<tt:Uri>{snapshot_url}</tt:Uri>"
        "<tt:InvalidAfterConnect>false</tt:InvalidAfterConnect>"
        "<tt:InvalidAfterReboot>false</tt:InvalidAfterReboot>"
        "<tt:Timeout>PT0S</tt:Timeout>"
        "</trt:MediaUri>"
        "</trt:GetSnapshotUriResponse>"
    )
    return _envelope(body)


def get_video_encoder_configurations() -> str:
    body = (
        "<trt:GetVideoEncoderConfigurationsResponse>"
        '<trt:Configurations token="VideoEncoder_0">'
        "<tt:Name>VideoEncoder</tt:Name>"
        "<tt:UseCount>1</tt:UseCount>"
        "<tt:Encoding>H264</tt:Encoding>"
        "<tt:Resolution><tt:Width>1920</tt:Width><tt:Height>1080</tt:Height></tt:Resolution>"
        "<tt:Quality>4</tt:Quality>"
        "</trt:Configurations>"
        "</trt:GetVideoEncoderConfigurationsResponse>"
    )
    return _envelope(body)


def fault(reason: str) -> str:
    body = (
        "<SOAP-ENV:Fault>"
        "<SOAP-ENV:Code><SOAP-ENV:Value>SOAP-ENV:Receiver</SOAP-ENV:Value></SOAP-ENV:Code>"
        f"<SOAP-ENV:Reason><SOAP-ENV:Text>{reason}</SOAP-ENV:Text></SOAP-ENV:Reason>"
        "</SOAP-ENV:Fault>"
    )
    return _envelope(body)
