import markdown
from bs4 import BeautifulSoup


def conversations_page_content(convs: dict) -> str:
    page_content = ""
    for index, item in enumerate(convs):
        page_content += f"{index+1}.\n*Title*: {item.get('title')}\n*ConversationID*: /{item.get('conversation_id')}\n\n"

    return page_content


def strip_markdown(md: str) -> str:
    html = markdown.markdown(md)
    soup = BeautifulSoup(html, features="html.parser")
    return soup.get_text()
