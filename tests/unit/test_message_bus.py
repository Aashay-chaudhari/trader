"""Tests for the message bus — the communication backbone."""

from agent_trader.core.message_bus import MessageBus, Message, MessageType


def test_publish_and_history():
    bus = MessageBus()
    msg = Message(type=MessageType.COMMAND, source="test", data={"foo": "bar"})
    bus.publish(msg)

    assert len(bus.history) == 1
    assert bus.history[0].source == "test"


def test_subscribe_callback():
    bus = MessageBus()
    received = []

    bus.subscribe(MessageType.SIGNAL, lambda m: received.append(m))

    # This should trigger the callback
    signal = Message(type=MessageType.SIGNAL, source="strategy", data={"action": "buy"})
    bus.publish(signal)

    # This should NOT trigger the callback (different type)
    command = Message(type=MessageType.COMMAND, source="orch", data={})
    bus.publish(command)

    assert len(received) == 1
    assert received[0].data["action"] == "buy"


def test_get_by_correlation():
    bus = MessageBus()

    cmd = Message(type=MessageType.COMMAND, source="orch", data={})
    bus.publish(cmd)

    response = Message(
        type=MessageType.RESULT, source="data", data={"prices": []},
        correlation_id=cmd.id,
    )
    bus.publish(response)

    related = bus.get_by_correlation(cmd.id)
    assert len(related) == 1
    assert related[0].type == MessageType.RESULT


def test_get_errors():
    bus = MessageBus()

    bus.publish(Message(type=MessageType.RESULT, source="a", data={}))
    bus.publish(Message(type=MessageType.ERROR, source="b", data={"error": "fail"}))
    bus.publish(Message(type=MessageType.ERROR, source="c", data={"error": "crash"}))

    errors = bus.get_errors()
    assert len(errors) == 2


def test_summary():
    bus = MessageBus()
    bus.publish(Message(type=MessageType.COMMAND, source="a", data={}))
    bus.publish(Message(type=MessageType.COMMAND, source="b", data={}))
    bus.publish(Message(type=MessageType.RESULT, source="c", data={}))

    summary = bus.summary()
    assert summary["command"] == 2
    assert summary["result"] == 1


def test_clear():
    bus = MessageBus()
    bus.publish(Message(type=MessageType.LOG, source="x", data={}))
    assert len(bus.history) == 1

    bus.clear()
    assert len(bus.history) == 0
