from django.contrib import admin
from django.utils.html import format_html
from django.http import HttpResponse
from .models import Participant, ParticipantSurvey, HandwritingSample
from .constants import TASK_CHARACTERS, TASK_OFFSETS
import zipfile
import io
import os
import json as json_module


def _get_char_index(task, character):
    chars = TASK_CHARACTERS.get(task, [])
    try:
        return chars.index(character) + TASK_OFFSETS.get(task, 1)
    except ValueError:
        return 0


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ['id', 'email', 'survey_done', 'created_at']
    search_fields = ['email']


@admin.register(ParticipantSurvey)
class SurveyAdmin(admin.ModelAdmin):
    list_display = ['participant', 'age', 'gender', 'handedness', 'region', 'created_at']
    search_fields = ['participant__email']


@admin.register(HandwritingSample)
class SampleAdmin(admin.ModelAdmin):
    list_display = ['participant_id_display', 'task', 'character_display',
                    'time_display', 'image_preview', 'created_at']
    list_filter = ['task', 'participant']
    search_fields = ['participant__email', 'character']
    readonly_fields = ['image_preview_large', 'time_display', 'stroke_data_pretty']
    actions = ['download_images_zip', 'download_strokes_zip', 'download_combined_zip']

    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        if search_term:
            queryset = queryset.filter(character=search_term) | \
                       queryset.filter(participant__email__icontains=search_term)
        return queryset, use_distinct

    def participant_id_display(self, obj):
        return f"P{obj.participant.id}"
    participant_id_display.short_description = 'ID'

    def character_display(self, obj):
        return format_html(
            '<span style="font-size:20px;font-family:serif;">{}</span>',
            obj.character
        )
    character_display.short_description = 'Character'

    # ── ZIP 1: Images only ──
    def download_images_zip(self, request, queryset):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            count = 0
            for sample in queryset:
                if sample.image:
                    try:
                        char_idx = _get_char_index(sample.task, sample.character)
                        participant_id = sample.participant.id
                        folder = f"{sample.task}/{char_idx}/{participant_id}_{char_idx}.png"

                        try:
                            image_path = sample.image.path
                            if os.path.exists(image_path):
                                zf.write(image_path, folder)
                                count += 1
                        except Exception:
                            import urllib.request
                            img_data = urllib.request.urlopen(sample.image.url).read()
                            zf.writestr(folder, img_data)
                            count += 1

                    except Exception as e:
                        print(f'[WARN] Image skip: {e}')

        if count == 0:
            self.message_user(request, 'No images found.', level='warning')
            return

        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename="handwriting_images.zip"'
        return response

    download_images_zip.short_description = '📷 Download selected — Images ZIP'

    # ── ZIP 2: Stroke JSON only ──
    def download_strokes_zip(self, request, queryset):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            count = 0
            for sample in queryset:
                try:
                    char_idx = _get_char_index(sample.task, sample.character)
                    participant_id = sample.participant.id
                    folder = f"{sample.task}/{char_idx}/{participant_id}_{char_idx}.json"

                    stroke_json = json_module.dumps({
                        'participant_id': participant_id,
                        'participant_email': sample.participant.email,
                        'char_index': char_idx,
                        'task': sample.task,
                        'character': sample.character,
                        'time_taken_ms': sample.time_taken,
                        'stroke_count': len(sample.stroke_data),
                        'total_points': sum(len(s) for s in sample.stroke_data),
                        'strokes': sample.stroke_data,
                    }, ensure_ascii=False, indent=2)

                    zf.writestr(folder, stroke_json)
                    count += 1

                except Exception as e:
                    print(f'[WARN] Stroke skip: {e}')

        if count == 0:
            self.message_user(request, 'No stroke data found.', level='warning')
            return

        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename="handwriting_strokes.zip"'
        return response

    download_strokes_zip.short_description = '✏️ Download selected — Strokes ZIP'

    # ── ZIP 3: Combined (Images + Strokes) ──
    def download_combined_zip(self, request, queryset):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            count = 0
            for sample in queryset:
                try:
                    char_idx = _get_char_index(sample.task, sample.character)
                    participant_id = sample.participant.id
                    base = f"{sample.task}/{char_idx}/{participant_id}_{char_idx}"

                    # Image
                    if sample.image:
                        try:
                            image_path = sample.image.path
                            if os.path.exists(image_path):
                                zf.write(image_path, f"{base}.png")
                            else:
                                raise FileNotFoundError
                        except Exception:
                            import urllib.request
                            img_data = urllib.request.urlopen(sample.image.url).read()
                            zf.writestr(f"{base}.png", img_data)

                    # Stroke JSON
                    stroke_json = json_module.dumps({
                        'participant_id': participant_id,
                        'participant_email': sample.participant.email,
                        'char_index': char_idx,
                        'task': sample.task,
                        'character': sample.character,
                        'time_taken_ms': sample.time_taken,
                        'stroke_count': len(sample.stroke_data),
                        'total_points': sum(len(s) for s in sample.stroke_data),
                        'strokes': sample.stroke_data,
                    }, ensure_ascii=False, indent=2)
                    zf.writestr(f"{base}.json", stroke_json)
                    count += 1

                except Exception as e:
                    print(f'[WARN] Combined skip: {e}')

        if count == 0:
            self.message_user(request, 'No data found.', level='warning')
            return

        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename="handwriting_combined.zip"'
        return response

    download_combined_zip.short_description = '📦 Download selected — Combined ZIP'

    def time_display(self, obj):
        ms = obj.time_taken
        if ms < 1000:
            return f'{ms}ms'
        seconds = ms // 1000
        if seconds < 60:
            return f'{seconds}s'
        minutes = seconds // 60
        remaining = seconds % 60
        return f'{minutes}m {remaining}s'
    time_display.short_description = 'Time Taken'

    def stroke_count(self, obj):
        return len(obj.stroke_data)
    stroke_count.short_description = 'Strokes'

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" width="60" height="60" style="border-radius:6px;object-fit:contain;background:#fff;"/>',
                obj.image.url,
            )
        return '—'
    image_preview.short_description = 'Preview'

    def image_preview_large(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" width="300" style="border-radius:10px;object-fit:contain;background:#fff;"/>',
                obj.image.url,
            )
        return '—'
    image_preview_large.short_description = 'Drawing'

    def stroke_data_pretty(self, obj):
        html = ''
        for i, stroke in enumerate(obj.stroke_data):
            html += f'<p><strong>Stroke {i+1}</strong> — {len(stroke)} points</p>'
            html += '<table style="border-collapse:collapse;margin-bottom:10px;font-size:12px;">'
            html += '<tr><th style="border:1px solid #ccc;padding:4px;">Point</th><th style="border:1px solid #ccc;padding:4px;">X</th><th style="border:1px solid #ccc;padding:4px;">Y</th><th style="border:1px solid #ccc;padding:4px;">Time (ms)</th></tr>'
            for j, point in enumerate(stroke):
                html += f'<tr><td style="border:1px solid #ccc;padding:4px;">{j+1}</td><td style="border:1px solid #ccc;padding:4px;">{point["x"]:.1f}</td><td style="border:1px solid #ccc;padding:4px;">{point["y"]:.1f}</td><td style="border:1px solid #ccc;padding:4px;">{point["t"]}</td></tr>'
            html += '</table>'
        return format_html(html)
    stroke_data_pretty.short_description = 'Stroke Data'

    fieldsets = (
        ('Sample Info', {'fields': ('participant', 'task', 'character', 'time_display')}),
        ('Drawing', {'fields': ('image', 'image_preview_large')}),
        ('Stroke Data', {'fields': ('stroke_data_pretty',)}),
    )