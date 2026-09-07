"""Package-local corrections for stock yt-dlp chapter removal.

Native ModifyChaptersPP remains responsible for media, SponsorBlock and atomic
replacement. Only its range input and external SRT cue timing are corrected.
"""
import os
import re

from yt_dlp.postprocessor import get_postprocessor
from yt_dlp.postprocessor.common import PostProcessor
from yt_dlp.postprocessor.modify_chapters import ModifyChaptersPP as _NativeModifyChaptersPP
from yt_dlp.utils import PostProcessingError, parse_duration, prepend_extension, srt_subtitles_timecode

__all__ = ["ModifyChaptersPP", "ErsatzRSChapterGuardPP"]


class ErsatzRSChapterGuardPP(PostProcessor):
    def run(self, info):
        if get_postprocessor('ModifyChapters') is not ModifyChaptersPP:
            raise PostProcessingError('The required package chapter processor is unavailable')
        return [], info


class ModifyChaptersPP(_NativeModifyChaptersPP):
    MAXIMUM_SRT_BYTES = 4 * 1024 * 1024

    def __init__(self, downloader, remove_ranges=None, **kwargs):
        super().__init__(downloader, remove_ranges=[tuple(value) for value in remove_ranges or []], **kwargs)
        self._edited_srt = set()

    def run(self, info):
        self._edited_srt.clear()
        files_to_remove, info = super().run(info)
        for language, subtitle in list((info.get('requested_subtitles') or {}).items()):
            path = subtitle.get('filepath')
            if path in self._edited_srt and os.path.getsize(path) == 0:
                os.remove(path)
                del info['requested_subtitles'][language]
                info.get('__files_to_move', {}).pop(path, None)
        return files_to_remove, info

    def remove_chapters(self, filename, ranges_to_cut, concat_opts, force_keyframes=False):
        if not filename.endswith('.srt'):
            return super().remove_chapters(filename, ranges_to_cut, concat_opts, force_keyframes)
        output = self.remove_srt_chapters(filename, concat_opts)
        self._edited_srt.add(filename)
        return output

    def remove_srt_chapters(self, filename, concat_opts):
        # Preserve payload and positioning verbatim: WebVTT conversion loses
        # SRT color/font/alignment. Parse all cues before creating any output.
        out_file = prepend_extension(filename, 'temp')
        timestamp = r'[0-9]{2,}:[0-5][0-9]:[0-5][0-9],[0-9]{3}'
        cues = []
        with open(filename, 'rb') as stream:
            source = stream.read(self.MAXIMUM_SRT_BYTES + 1)
        if len(source) > self.MAXIMUM_SRT_BYTES:
            raise PostProcessingError('Subtitle source exceeds the package byte limit')
        content = source.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n').strip('\n')
        for block in re.split(r'\n(?:[ \t]*\n)+', content) if content else []:
            if not block.strip():
                continue
            match = re.fullmatch(
                rf'[0-9]+\n({timestamp})[ \t]+-->[ \t]+({timestamp})([^\n]*)\n([\s\S]+)', block)
            if not match:
                raise PostProcessingError('Unsupported SRT cue syntax; original subtitles were not changed')
            start, end = (round(parse_duration(value.replace(',', '.')) * 1000)
                          for value in match.group(1, 2))
            if end < start:
                raise PostProcessingError('Invalid SRT cue interval; original subtitles were not changed')
            cues.append((start, end, match.group(3), match.group(4)))
        offset, index, written = 0, 0, 0
        # Never accumulate the expanded cue set: a spanning cue may be split
        # across every retained interval. Bound encoded bytes before each write.
        with open(out_file, 'wb') as stream:
            try:
                for interval in concat_opts:
                    start = round(float(interval.get('inpoint', 0)) * 1000)
                    end = (round(float(interval['outpoint']) * 1000)
                           if 'outpoint' in interval else float('inf'))
                    for cue_start, cue_end, settings, text in cues:
                        left, right = max(cue_start, start), min(cue_end, end)
                        if left >= right:
                            continue
                        index += 1
                        block = (f'{index}\n{srt_subtitles_timecode((offset + left - start) / 1000)} --> '
                                 f'{srt_subtitles_timecode((offset + right - start) / 1000)}'
                                 f'{settings}\n{text}\n\n').encode('utf-8')
                        if written + len(block) > self.MAXIMUM_SRT_BYTES:
                            raise PostProcessingError('Edited subtitle exceeds the package byte limit')
                        stream.write(block)
                        written += len(block)
                    offset += end - start
            except Exception:
                # Close before unlinking for Windows; native replacement has
                # not started, so the original source remains intact.
                stream.close()
                os.remove(out_file)
                raise
        return out_file
