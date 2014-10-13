from enum import Enum


class LayerType(Enum):
    __order__ = 'Polling State Parliament'  # only needed in 2.x
    Polling = 1
    State = 2
    Parliament = 4