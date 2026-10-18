import base64
import io

from PIL import Image

from findocs import llm

OCR_PROMPT = (
    "Перепиши весь печатный текст с этого скана документа дословно, сверху вниз. "
    "Таблицы — построчно, ячейки через ' | '.\n"
    "В конце перечисли печати и штампы: каждая печать целиком — одной строкой с префиксом [печать]. "
    "Переписывай только то, что на печати действительно читается; текст по кругу, который не читается, пропускай.\n"
    "Затем рукописные пометки: каждая пометка целиком — одной строкой с префиксом [рукопись], "
    "даже если она написана в несколько строк. Подписи-росчерки не переписывай.\n"
    "Ничего не добавляй, не исправляй и не дописывай. Если символ не читается, ставь [?]."
)


def _to_data_url(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def ocr_page(image: Image.Image) -> llm.LLMResult:
    return llm.chat([{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": _to_data_url(image)}},
            {"type": "text", "text": OCR_PROMPT},
        ],
    }])
