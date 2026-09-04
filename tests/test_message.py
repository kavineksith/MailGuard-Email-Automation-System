import pickle

from models.message import EmailMessage, MessageStatus


def make_message(**overrides):
    defaults = dict(
        subject="Hello",
        body="World",
        recipients=["a@example.com"],
        sender="me@example.com",
    )
    defaults.update(overrides)
    return EmailMessage(**defaults)


def test_all_recipients_combines_to_cc_bcc():
    msg = make_message(cc=["c@example.com"], bcc=["b@example.com"])
    assert msg.all_recipients() == ["a@example.com", "c@example.com", "b@example.com"]


def test_len_and_contains():
    msg = make_message(cc=["c@example.com"])
    assert len(msg) == 2
    assert "c@example.com" in msg


def test_iter_yields_recipients():
    msg = make_message(cc=["c@example.com"])
    assert list(iter(msg)) == msg.all_recipients()


def test_getitem():
    msg = make_message()
    assert msg[0] == "a@example.com"


def test_bool_false_without_recipients():
    msg = make_message(recipients=[])
    assert bool(msg) is False


def test_bool_true_with_subject_and_recipient():
    msg = make_message()
    assert bool(msg) is True


def test_equality_by_message_id():
    msg1 = make_message()
    msg2 = make_message()
    assert msg1 != msg2  # distinct UUIDs
    assert msg1 == msg1


def test_hash_stable():
    msg = make_message()
    assert hash(msg) == hash(msg.message_id)


def test_ordering_by_created_at():
    msg1 = make_message()
    msg2 = make_message()
    assert (msg1 < msg2) or (msg2 < msg1) or (msg1.created_at == msg2.created_at)


def test_terminal_status_uses_is_not_none_semantics():
    msg = make_message()
    assert not msg.is_terminal()
    msg.mark(MessageStatus.SENT)
    assert msg.is_terminal()


def test_pickle_roundtrip_preserves_status_enum():
    msg = make_message()
    msg.mark(MessageStatus.FAILED)
    restored = pickle.loads(pickle.dumps(msg))
    assert restored.status == MessageStatus.FAILED
    assert isinstance(restored.status, MessageStatus)


def test_clone_for_retry_generates_new_id_and_resets_status():
    msg = make_message()
    msg.mark(MessageStatus.FAILED)
    clone = msg.clone_for_retry()
    assert clone.message_id != msg.message_id
    assert clone.status == MessageStatus.PENDING


def test_to_dict_contains_expected_keys():
    msg = make_message()
    data = msg.to_dict()
    assert set(["message_id", "subject", "recipients", "status"]).issubset(data.keys())
