"""Bidwright: an agentic RFP-to-proposal system."""

import logging

__version__ = "0.2.0"

# D-05: at DEBUG, pdfminer (under pdfplumber and guard's PDF scan) logs every token of a PDF's
# content streams, and the OpenAI SDK logs each request body, so either would copy document
# text into the logs. Their loggers stay at WARNING whatever level the root logger has.
for _name in ("pdfminer", "openai"):
    logging.getLogger(_name).setLevel(logging.WARNING)
