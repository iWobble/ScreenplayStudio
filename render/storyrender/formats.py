"""Where a film is going: the picture shape, the loudness and the length a platform takes. The story says which (its `format`, `loudness` and `platform`
fields); everything here is a plain table so a platform's rules can be changed in one place. Platform limits move over time: the message says
to check the platform's current one."""

SHAPES = {
    "short-9x16": (1080, 1920),  # YouTube Shorts, Instagram Reels, TikTok
    "square-1x1": (1080, 1080),  # a feed post
    "portrait-4x5": (1080, 1350),  # an Instagram feed post that fills the most of the screen
    "wide-16x9": (1920, 1080),  # a regular YouTube video
}
DEFAULT_SHAPE = "short-9x16"

# Integrated loudness targets in LUFS. -16 is the renderer's long-standing default; the big platforms normalise to about -14.
LOUDNESS = {"-14": -14.0, "-16": -16.0, "-23": -23.0}
DEFAULT_LOUDNESS = -16.0

# platform → (what to call it, the longest film it takes in seconds, or None for no limit worth warning about)
PLATFORMS = {
    "youtube-short": ("a YouTube Short", 180),
    "instagram-reel": ("an Instagram Reel", 180),
    "tiktok": ("a TikTok", 600),
    "instagram-feed": ("an Instagram feed video", 180),
    "youtube": ("a YouTube video", None),
}


def size_of(story: dict) -> tuple[int, int] | None:
    """The picture size the story's `format` names, or None when it names none (the default: a vertical Short)."""
    return SHAPES.get(str(story.get("format") or "").strip().lower())


def loudness_of(story: dict) -> float | None:
    """The loudness target the story's `loudness` names (LUFS), or None for the default."""
    return LOUDNESS.get(str(story.get("loudness") or "").strip())


def timecode(seconds: float) -> str:
    whole = round(seconds)
    return f"{whole // 60}:{whole % 60:02d}"


def length_warning(seconds: float, story: dict) -> str | None:
    """Words for a film that runs past what its platform takes, or None when it fits (or no platform is named)."""
    name, limit = PLATFORMS.get(str(story.get("platform") or "").strip().lower(), (None, None))
    if name is None or limit is None or seconds <= limit:
        return None
    return f"This film is {timecode(seconds)} and {name} may run to {timecode(limit)} (check the platform's current limit): shorten it, or choose a different platform."
