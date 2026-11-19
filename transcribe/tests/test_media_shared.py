"""Since P6 the model loading, the sound check and the transcript's text forms are the Media package's (`mediajobs`), not copies: one worker
keeps one copy of a model for Studio's kinds and Media's media-transcribe. How the model is RUN stays Studio's (`transcribe_file`,
`heard_words`): Media's runs it once with word times, which can cut the segments differently, so sharing that would change Studio's output."""

from mediajobs import text as m_text
from mediajobs import transcribe as m_transcribe

from storytranscribe import jobs, text


def test_the_shared_helpers_are_medias():
    assert text is m_text and jobs.text is m_text
    assert jobs.load_model is m_transcribe.load_model and jobs.has_sound is m_transcribe.has_sound and jobs.MODEL == m_transcribe.MODEL


def test_how_the_model_is_run_stays_studios():
    assert jobs.transcribe_file is not m_transcribe.transcribe_file and jobs.transcribe_file.__module__ == "storytranscribe.jobs"
    assert jobs.heard_words.__module__ == "storytranscribe.jobs"
