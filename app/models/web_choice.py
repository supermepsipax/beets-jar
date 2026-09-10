import enum
from beets.autotag import TrackMatch, AlbumMatch
from beets.util import PromptChoice

class ChoiceType(str, enum.Enum):
    SKIP = "s"
    ASIS = "u"
    AS_TRACKS = "t"
    GROUP_ALBUMS = "g"
    SEARCH = "e"
    ID = "i"
    ABORT = "b"

class DuplicateChoiceType(str, enum.Enum):
    
    SKIP = "s"
    MERGE = "m"
    REMOVE = "r"
    KEEP = "k"

class WebChoice:
    def __init__(self, choice: AlbumMatch | TrackMatch | PromptChoice, follow_up_info: dict[str, str]):
        self.choice = choice
        self.follow_up_info = follow_up_info
