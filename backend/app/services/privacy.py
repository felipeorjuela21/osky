"""Personal data minimisation (Ley 1581 de 2012).

Visitors sometimes say their phone, e-mail or ID number in a question. Osky does
not need them to answer, so they are replaced before the text is stored or sent
to the language model (as Salesforce's Einstein Trust Layer masks PII).
"""
import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
# 7+ digits, allowing spaces, dots or dashes between groups: phones, cédulas, NIT, cards.
LONG_NUMBER = re.compile(r"(?<![\w$])\+?\d(?:[\s.-]?\d){6,}(?![\w%])")

def redact(text: str) -> str:
    text = EMAIL.sub("[correo]", text)
    return LONG_NUMBER.sub("[número]", text)
