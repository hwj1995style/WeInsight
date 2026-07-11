from app.rpa.wxauto_client import WxautoGroupRpaClient


class FakeWx:
    def __init__(self) -> None:
        self.chats: list[str] = []
        self.scrolls = 0

    def ChatWith(self, name: str) -> None:
        self.chats.append(name)

    def GetAllMessage(self):
        return [{"sender": "Alice", "content": "hello", "time": "10:00"}]

    def ScrollUp(self) -> None:
        self.scrolls += 1


def test_wxauto_group_client_normalizes_messages() -> None:
    wx = FakeWx()
    client = WxautoGroupRpaClient(wx=wx)
    client.open_group("群聊")
    message = client.read_visible_messages()[0]
    assert (message.group_name, message.sender_name, message.msg_content) == ("群聊", "Alice", "hello")


def test_wxauto_group_client_scrolls_requested_pages() -> None:
    wx = FakeWx()
    WxautoGroupRpaClient(wx=wx).scroll_up_messages(3)
    assert wx.scrolls == 3
