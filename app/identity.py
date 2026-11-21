# 承运人身份边界（批次接入裁决：只在本承运人范围内复用）
#
# 裁决结论：拒绝按文件内容做全局复用。相同舱单内容在不同承运人名下
# 各自形成独立批次，互不可见；同一承运人重试相同内容仍只保留一条批次。
#
# 身份来源（按优先级）：
#   1. HTTP 头 X-Carrier-Id
#   2. 查询参数 carrier_id
#   3. 缺省演示承运人 DEMO-CARRIER（仅离线演示/兼容旧调用）
import re
from app.errors import BusinessError

DEFAULT_CARRIER = 'DEMO-CARRIER'
CARRIER_HEADER = 'X-Carrier-Id'
CARRIER_PARAM = 'carrier_id'
# 承运人编号：大写字母、数字、短横线，2~40 位，避免注入与头伪造歧义
_CARRIER_RE = re.compile(r'^[A-Z0-9][A-Z0-9-]{1,39}$')


def normalize_carrier(value):
    """规范化并校验承运人编号；非法值直接拒绝，不静默落到默认承运人。"""
    if value is None:
        return DEFAULT_CARRIER
    carrier = str(value).strip().upper()
    if not _CARRIER_RE.match(carrier):
        raise BusinessError(
            'BAD_CARRIER',
            '承运人编号须为2~40位大写字母、数字或短横线，且以字母或数字开头',
            400,
        )
    return carrier


def carrier_from_request(request):
    raw = request.headers.get(CARRIER_HEADER) or request.query_params.get(CARRIER_PARAM)
    return normalize_carrier(raw)
