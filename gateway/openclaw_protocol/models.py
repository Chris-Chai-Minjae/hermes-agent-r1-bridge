"""Pydantic wire models for the OpenClaw gateway protocol subset Hermes needs."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator
from pydantic.types import StringConstraints

NonEmptyString = Annotated[str, StringConstraints(min_length=1)]
PROTOCOL_VERSION = 3

ErrorCode = Literal[
    "NOT_LINKED",
    "NOT_PAIRED",
    "AGENT_TIMEOUT",
    "INVALID_REQUEST",
    "APPROVAL_NOT_FOUND",
    "UNAVAILABLE",
]

GatewayClientId = Literal[
    "webchat-ui",
    "openclaw-control-ui",
    "openclaw-tui",
    "webchat",
    "cli",
    "gateway-client",
    "openclaw-macos",
    "openclaw-ios",
    "openclaw-android",
    "node-host",
    "test",
    "fingerprint",
    "openclaw-probe",
]

GatewayClientMode = Literal[
    "webchat",
    "cli",
    "ui",
    "backend",
    "node",
    "probe",
    "test",
]


class GatewayClientIds:
    WEBCHAT_UI: GatewayClientId = "webchat-ui"
    CONTROL_UI: GatewayClientId = "openclaw-control-ui"
    TUI: GatewayClientId = "openclaw-tui"
    WEBCHAT: GatewayClientId = "webchat"
    CLI: GatewayClientId = "cli"
    GATEWAY_CLIENT: GatewayClientId = "gateway-client"
    MACOS_APP: GatewayClientId = "openclaw-macos"
    IOS_APP: GatewayClientId = "openclaw-ios"
    ANDROID_APP: GatewayClientId = "openclaw-android"
    NODE_HOST: GatewayClientId = "node-host"
    TEST: GatewayClientId = "test"
    FINGERPRINT: GatewayClientId = "fingerprint"
    PROBE: GatewayClientId = "openclaw-probe"


class GatewayClientModes:
    WEBCHAT: GatewayClientMode = "webchat"
    CLI: GatewayClientMode = "cli"
    UI: GatewayClientMode = "ui"
    BACKEND: GatewayClientMode = "backend"
    NODE: GatewayClientMode = "node"
    PROBE: GatewayClientMode = "probe"
    TEST: GatewayClientMode = "test"


class ErrorCodes:
    NOT_LINKED: ErrorCode = "NOT_LINKED"
    NOT_PAIRED: ErrorCode = "NOT_PAIRED"
    AGENT_TIMEOUT: ErrorCode = "AGENT_TIMEOUT"
    INVALID_REQUEST: ErrorCode = "INVALID_REQUEST"
    APPROVAL_NOT_FOUND: ErrorCode = "APPROVAL_NOT_FOUND"
    UNAVAILABLE: ErrorCode = "UNAVAILABLE"


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConnectChallengePayload(WireModel):
    nonce: NonEmptyString
    ts: int = Field(ge=0)


class TickEventPayload(WireModel):
    ts: int = Field(ge=0)


class ShutdownEventPayload(WireModel):
    reason: NonEmptyString
    restartExpectedMs: Optional[int] = Field(default=None, ge=0)


class GatewayClientInfo(WireModel):
    id: GatewayClientId
    version: NonEmptyString
    platform: NonEmptyString
    mode: GatewayClientMode
    displayName: Optional[NonEmptyString] = None
    deviceFamily: Optional[NonEmptyString] = None
    modelIdentifier: Optional[NonEmptyString] = None
    instanceId: Optional[NonEmptyString] = None


class ConnectDeviceIdentity(WireModel):
    id: NonEmptyString
    publicKey: NonEmptyString
    signature: NonEmptyString
    signedAt: int = Field(ge=0)
    nonce: NonEmptyString


class ConnectAuth(WireModel):
    token: Optional[str] = None
    bootstrapToken: Optional[str] = None
    deviceToken: Optional[str] = None
    password: Optional[str] = None


class ConnectParams(WireModel):
    minProtocol: int = Field(ge=1)
    maxProtocol: int = Field(ge=1)
    client: GatewayClientInfo
    caps: list[NonEmptyString] = Field(default_factory=list)
    commands: Optional[list[NonEmptyString]] = None
    permissions: Optional[dict[NonEmptyString, bool]] = None
    pathEnv: Optional[str] = None
    role: Optional[NonEmptyString] = None
    scopes: Optional[list[NonEmptyString]] = None
    device: Optional[ConnectDeviceIdentity] = None
    auth: Optional[ConnectAuth] = None
    locale: Optional[str] = None
    userAgent: Optional[str] = None


class PresenceEntry(WireModel):
    host: Optional[NonEmptyString] = None
    ip: Optional[NonEmptyString] = None
    version: Optional[NonEmptyString] = None
    platform: Optional[NonEmptyString] = None
    deviceFamily: Optional[NonEmptyString] = None
    modelIdentifier: Optional[NonEmptyString] = None
    mode: Optional[NonEmptyString] = None
    lastInputSeconds: Optional[int] = Field(default=None, ge=0)
    reason: Optional[NonEmptyString] = None
    tags: Optional[list[NonEmptyString]] = None
    text: Optional[str] = None
    ts: int = Field(ge=0)
    deviceId: Optional[NonEmptyString] = None
    roles: Optional[list[NonEmptyString]] = None
    scopes: Optional[list[NonEmptyString]] = None
    instanceId: Optional[NonEmptyString] = None


class StateVersion(WireModel):
    presence: int = Field(ge=0)
    health: int = Field(ge=0)


class SessionDefaults(WireModel):
    defaultAgentId: NonEmptyString
    mainKey: NonEmptyString
    mainSessionKey: NonEmptyString
    scope: Optional[NonEmptyString] = None


class UpdateAvailable(WireModel):
    currentVersion: NonEmptyString
    latestVersion: NonEmptyString
    channel: NonEmptyString


class Snapshot(WireModel):
    presence: list[PresenceEntry]
    health: Any
    stateVersion: StateVersion
    uptimeMs: int = Field(ge=0)
    configPath: Optional[NonEmptyString] = None
    stateDir: Optional[NonEmptyString] = None
    sessionDefaults: Optional[SessionDefaults] = None
    authMode: Optional[Literal["none", "token", "password", "trusted-proxy"]] = None
    updateAvailable: Optional[UpdateAvailable] = None


class HelloOkAuthToken(WireModel):
    deviceToken: NonEmptyString
    role: NonEmptyString
    scopes: list[NonEmptyString]
    issuedAtMs: int = Field(ge=0)


class HelloOkAuth(WireModel):
    deviceToken: Optional[NonEmptyString] = None
    role: NonEmptyString
    scopes: list[NonEmptyString]
    issuedAtMs: Optional[int] = Field(default=None, ge=0)
    deviceTokens: Optional[list[HelloOkAuthToken]] = None


class HelloOkServer(WireModel):
    version: NonEmptyString
    connId: NonEmptyString


class HelloOkFeatures(WireModel):
    methods: list[NonEmptyString]
    events: list[NonEmptyString]


class HelloOkPolicy(WireModel):
    maxPayload: int = Field(ge=1)
    maxBufferedBytes: int = Field(ge=1)
    tickIntervalMs: int = Field(ge=1)


class HelloOk(WireModel):
    type: Literal["hello-ok"]
    protocol: int = Field(ge=1)
    server: HelloOkServer
    features: HelloOkFeatures
    snapshot: Snapshot
    canvasHostUrl: Optional[NonEmptyString] = None
    auth: Optional[HelloOkAuth] = None
    policy: HelloOkPolicy


class ErrorShape(WireModel):
    code: Union[ErrorCode, NonEmptyString]
    message: NonEmptyString
    details: Optional[Any] = None
    retryable: Optional[bool] = None
    retryAfterMs: Optional[int] = Field(default=None, ge=0)


class RequestFrame(WireModel):
    type: Literal["req"]
    id: NonEmptyString
    method: NonEmptyString
    params: Optional[Any] = None


class ConnectRequestFrame(WireModel):
    type: Literal["req"]
    id: NonEmptyString
    method: Literal["connect"]
    params: ConnectParams


class ResponseFrame(WireModel):
    type: Literal["res"]
    id: NonEmptyString
    ok: bool
    payload: Optional[Any] = None
    error: Optional[ErrorShape] = None

    @field_validator("error")
    @classmethod
    def _validate_error_consistency(cls, value: Optional[ErrorShape], info: Any) -> Optional[ErrorShape]:
        if value is not None and info.data.get("ok") is True:
            raise ValueError("successful responses must not include error")
        return value


class HelloOkResponseFrame(WireModel):
    type: Literal["res"]
    id: NonEmptyString
    ok: Literal[True]
    payload: HelloOk
    error: None = None


class EventFrame(WireModel):
    type: Literal["event"]
    event: NonEmptyString
    payload: Optional[Any] = None
    seq: Optional[int] = Field(default=None, ge=0)
    stateVersion: Optional[StateVersion] = None


class ConnectChallengeEvent(WireModel):
    type: Literal["event"]
    event: Literal["connect.challenge"]
    payload: ConnectChallengePayload
    seq: Optional[int] = Field(default=None, ge=0)
    stateVersion: Optional[StateVersion] = None


class TickEvent(WireModel):
    type: Literal["event"]
    event: Literal["tick"]
    payload: TickEventPayload
    seq: Optional[int] = Field(default=None, ge=0)
    stateVersion: Optional[StateVersion] = None


class ShutdownEvent(WireModel):
    type: Literal["event"]
    event: Literal["shutdown"]
    payload: ShutdownEventPayload
    seq: Optional[int] = Field(default=None, ge=0)
    stateVersion: Optional[StateVersion] = None


class DevicePairListParams(WireModel):
    pass


class DevicePairApproveParams(WireModel):
    requestId: NonEmptyString


class DevicePairRejectParams(WireModel):
    requestId: NonEmptyString


class DevicePairRemoveParams(WireModel):
    deviceId: NonEmptyString


class DeviceTokenRotateParams(WireModel):
    deviceId: NonEmptyString
    role: NonEmptyString
    scopes: Optional[list[NonEmptyString]] = None


class DeviceTokenRevokeParams(WireModel):
    deviceId: NonEmptyString
    role: NonEmptyString


class DevicePairRequestedPayload(WireModel):
    requestId: NonEmptyString
    deviceId: NonEmptyString
    publicKey: NonEmptyString
    displayName: Optional[NonEmptyString] = None
    platform: Optional[NonEmptyString] = None
    deviceFamily: Optional[NonEmptyString] = None
    clientId: Optional[NonEmptyString] = None
    clientMode: Optional[NonEmptyString] = None
    role: Optional[NonEmptyString] = None
    roles: Optional[list[NonEmptyString]] = None
    scopes: Optional[list[NonEmptyString]] = None
    remoteIp: Optional[NonEmptyString] = None
    silent: Optional[bool] = None
    isRepair: Optional[bool] = None
    ts: int = Field(ge=0)


class DevicePairResolvedPayload(WireModel):
    requestId: NonEmptyString
    deviceId: NonEmptyString
    decision: NonEmptyString
    ts: int = Field(ge=0)


class DevicePairRequestedEvent(WireModel):
    type: Literal["event"]
    event: Literal["device.pair.requested"]
    payload: DevicePairRequestedPayload
    seq: Optional[int] = Field(default=None, ge=0)
    stateVersion: Optional[StateVersion] = None


class DevicePairResolvedEvent(WireModel):
    type: Literal["event"]
    event: Literal["device.pair.resolved"]
    payload: DevicePairResolvedPayload
    seq: Optional[int] = Field(default=None, ge=0)
    stateVersion: Optional[StateVersion] = None


class NodePairRequestParams(WireModel):
    nodeId: NonEmptyString
    displayName: Optional[NonEmptyString] = None
    platform: Optional[NonEmptyString] = None
    version: Optional[NonEmptyString] = None
    coreVersion: Optional[NonEmptyString] = None
    uiVersion: Optional[NonEmptyString] = None
    deviceFamily: Optional[NonEmptyString] = None
    modelIdentifier: Optional[NonEmptyString] = None
    caps: Optional[list[NonEmptyString]] = None
    commands: Optional[list[NonEmptyString]] = None
    permissions: Optional[dict[NonEmptyString, bool]] = None
    remoteIp: Optional[NonEmptyString] = None
    silent: Optional[bool] = None


class NodePairApproveParams(WireModel):
    requestId: NonEmptyString


class NodePairRejectParams(WireModel):
    requestId: NonEmptyString


class NodePairVerifyParams(WireModel):
    nodeId: NonEmptyString
    token: NonEmptyString


class NodeRenameParams(WireModel):
    nodeId: NonEmptyString
    displayName: NonEmptyString


class NodeListParams(WireModel):
    pass


class NodePendingAckParams(WireModel):
    ids: list[NonEmptyString] = Field(min_length=1)


class NodeDescribeParams(WireModel):
    nodeId: NonEmptyString


class NodeInvokeParams(WireModel):
    nodeId: NonEmptyString
    command: NonEmptyString
    params: Optional[Any] = None
    timeoutMs: Optional[int] = Field(default=None, ge=0)
    idempotencyKey: NonEmptyString


class NodeInvokeError(WireModel):
    code: Optional[NonEmptyString] = None
    message: Optional[NonEmptyString] = None


class NodeInvokeResultParams(WireModel):
    id: NonEmptyString
    nodeId: NonEmptyString
    ok: bool
    payload: Optional[Any] = None
    payloadJSON: Optional[str] = None
    error: Optional[NodeInvokeError] = None


class NodeEventParams(WireModel):
    event: NonEmptyString
    payload: Optional[Any] = None
    payloadJSON: Optional[str] = None


class NodePendingDrainParams(WireModel):
    maxItems: Optional[int] = Field(default=None, ge=1, le=10)


class NodePendingDrainItem(WireModel):
    id: NonEmptyString
    type: Literal["status.request", "location.request"]
    priority: Literal["default", "normal", "high"]
    createdAtMs: int = Field(ge=0)
    expiresAtMs: Optional[int] = Field(default=None, ge=0)
    payload: Optional[dict[str, Any]] = None


class NodePendingDrainResult(WireModel):
    nodeId: NonEmptyString
    revision: int = Field(ge=0)
    items: list[NodePendingDrainItem]
    hasMore: bool


class NodePendingEnqueueParams(WireModel):
    nodeId: NonEmptyString
    type: Literal["status.request", "location.request"]
    priority: Optional[Literal["normal", "high"]] = None
    expiresInMs: Optional[int] = Field(default=None, ge=1_000, le=86_400_000)
    wake: Optional[bool] = None


class NodePendingEnqueueResult(WireModel):
    nodeId: NonEmptyString
    revision: int = Field(ge=0)
    queued: NodePendingDrainItem
    wakeTriggered: bool


class NodeInvokeRequestEventPayload(WireModel):
    id: NonEmptyString
    nodeId: NonEmptyString
    command: NonEmptyString
    paramsJSON: Optional[str] = None
    timeoutMs: Optional[int] = Field(default=None, ge=0)
    idempotencyKey: Optional[NonEmptyString] = None


class NodeInvokeRequestEvent(WireModel):
    type: Literal["event"]
    event: Literal["node.invoke.request"]
    payload: NodeInvokeRequestEventPayload
    seq: Optional[int] = Field(default=None, ge=0)
    stateVersion: Optional[StateVersion] = None


class VoiceTranscriptPayload(WireModel):
    text: NonEmptyString
    sessionKey: Optional[NonEmptyString] = None
    eventId: Optional[NonEmptyString] = None
    providerEventId: Optional[NonEmptyString] = None
    transcriptId: Optional[NonEmptyString] = None
    callId: Optional[NonEmptyString] = None
    providerCallId: Optional[NonEmptyString] = None
    sequence: Optional[int] = None
    seq: Optional[int] = None
    timestamp: Optional[int] = None
    ts: Optional[int] = None
    eventTimestamp: Optional[int] = None


class NodePairPendingRequest(NodePairRequestParams):
    requestId: NonEmptyString
    ts: int = Field(ge=0)


class NodePairPendingEntry(NodePairPendingRequest):
    requiredApproveScopes: list[NonEmptyString]


class NodePairPairedNode(NodePairRequestParams):
    nodeId: NonEmptyString
    token: NonEmptyString
    bins: Optional[list[NonEmptyString]] = None
    createdAtMs: int = Field(ge=0)
    approvedAtMs: int = Field(ge=0)
    lastConnectedAtMs: Optional[int] = Field(default=None, ge=0)


class NodePairList(WireModel):
    pending: list[NodePairPendingEntry]
    paired: list[NodePairPairedNode]


class NodePairRequestResult(WireModel):
    status: Literal["pending"]
    request: NodePairPendingRequest
    created: bool


class NodePairApproveResult(WireModel):
    requestId: NonEmptyString
    node: NodePairPairedNode


class NodePairVerifyResult(WireModel):
    ok: bool
    node: Optional[NodePairPairedNode] = None


class NodePairRequestedEvent(WireModel):
    type: Literal["event"]
    event: Literal["node.pair.requested"]
    payload: NodePairPendingRequest
    seq: Optional[int] = Field(default=None, ge=0)
    stateVersion: Optional[StateVersion] = None


class NodePairResolvedPayload(WireModel):
    requestId: NonEmptyString
    nodeId: NonEmptyString
    decision: Literal["approved", "rejected", "expired"]
    ts: int = Field(ge=0)


class NodePairResolvedEvent(WireModel):
    type: Literal["event"]
    event: Literal["node.pair.resolved"]
    payload: NodePairResolvedPayload
    seq: Optional[int] = Field(default=None, ge=0)
    stateVersion: Optional[StateVersion] = None


GatewayFrame = Union[
    ConnectRequestFrame,
    HelloOkResponseFrame,
    ConnectChallengeEvent,
    TickEvent,
    ShutdownEvent,
    DevicePairRequestedEvent,
    DevicePairResolvedEvent,
    NodeInvokeRequestEvent,
    RequestFrame,
    ResponseFrame,
    EventFrame,
]
_gateway_frame_adapter = TypeAdapter(GatewayFrame)


def parse_gateway_frame(data: Any) -> GatewayFrame:
    return _gateway_frame_adapter.validate_python(data)
