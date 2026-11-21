import logging
from enum import Enum

from attr import dataclass


class LogLevel(Enum):
    CRASHING = logging.FATAL
    ERRORING = logging.ERROR
    WARNING = logging.WARNING
    INFORMATION = logging.INFO
    DEBUGGING = logging.DEBUG


@dataclass
class Logger:
    level: LogLevel
    format: str = "%(levelname)s %(name)s: %(message)s"

    def configure(self) -> None:
        logging.basicConfig(level=self.level.value, format=self.format)
