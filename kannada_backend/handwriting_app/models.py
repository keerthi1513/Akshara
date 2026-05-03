import os
import random
from django.db import models
from django.utils import timezone
from datetime import timedelta
from .constants import TASK_CHARACTERS, TASK_OFFSETS


def handwriting_upload_path(instance, filename):
    ext = filename.split('.')[-1]
    task = instance.task
    character = instance.character
    participant_id = instance.participant.id

    chars = TASK_CHARACTERS.get(task, [])
    try:
        char_index = chars.index(character) + TASK_OFFSETS.get(task, 1)
    except ValueError:
        char_index = 0

    filename = f"{participant_id}_{char_index}.{ext}"
    return os.path.join('dataset', task, str(char_index), filename)


class Participant(models.Model):
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255)
    survey_done = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return self.email


class ParticipantSurvey(models.Model):
    HANDEDNESS_CHOICES = [('right', 'Right'), ('left', 'Left'), ('both', 'Both')]

    participant = models.OneToOneField(Participant, on_delete=models.CASCADE, related_name='survey')
    age = models.PositiveIntegerField()
    gender = models.CharField(max_length=20, blank=True)
    handedness = models.CharField(max_length=10, choices=HANDEDNESS_CHOICES)
    native_language = models.CharField(max_length=50, blank=True)
    hometown = models.CharField(max_length=100, blank=True)
    mother_tongue = models.CharField(max_length=10, blank=True)
    education_level = models.CharField(max_length=100, blank=True)
    region = models.CharField(max_length=100, blank=True)
    writing_fluency = models.CharField(max_length=50, blank=True)
    reading_fluency = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Survey — {self.participant.email}"


class HandwritingSample(models.Model):
    TASK_CHOICES = [
        ('vowels', 'Vowels'),
        ('consonants', 'Consonants'),
        ('conjuncts', 'Conjuncts'),
        ('kagunitas', 'Kagunitas'),
    ]

    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name='samples')
    task = models.CharField(max_length=20, choices=TASK_CHOICES)
    character = models.CharField(max_length=10)
    image = models.ImageField(upload_to=handwriting_upload_path, null=True, blank=True)
    stroke_data = models.JSONField()
    time_taken = models.IntegerField(help_text='Time taken in milliseconds')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['task', 'character', 'created_at']
        unique_together = ('participant', 'task', 'character')

    def __str__(self):
        return f"{self.character} [{self.task}] — {self.participant.email}"


class OTPCode(models.Model):
    email = models.EmailField()
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(minutes=10)

    def __str__(self):
        return f"{self.email} — {self.code}"