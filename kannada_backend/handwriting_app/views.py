import json
import base64
import uuid
import hashlib
import os
import random
import string
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.files.base import ContentFile
from django.db import IntegrityError
from .models import HandwritingSample, Participant, ParticipantSurvey
from .constants import TASK_CHARACTERS, TASK_ORDER, TASK_OFFSETS
from django.core.mail import send_mail, EmailMultiAlternatives
from django.conf import settings
from .models import OTPCode


def _json(data, status=200):
    return JsonResponse(data, status=status)


def _parse(request):
    try:
        return json.loads(request.body), None
    except json.JSONDecodeError:
        return None, _json({'error': 'Invalid JSON'}, 400)


def _hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def _generate_temp_password(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


# POST /api/register/
@csrf_exempt
def register(request):
    if request.method != 'POST':
        return _json({'error': 'POST required'}, 405)
    data, err = _parse(request)
    if err:
        return err

    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()

    if not email or not password:
        return _json({'error': 'email and password are required'}, 400)
    if len(password) < 6:
        return _json({'error': 'Password must be at least 6 characters'}, 400)

    if Participant.objects.filter(email=email).exists():
        return _json({'error': 'Email already registered. Please login.'}, 409)

    participant = Participant.objects.create(
        email=email,
        password=_hash_password(password),
    )
    return _json({
        'participant_id': participant.id,
        'email': participant.email,
        'survey_done': participant.survey_done,
    }, 201)


# POST /api/login/
@csrf_exempt
def login(request):
    if request.method != 'POST':
        return _json({'error': 'POST required'}, 405)
    data, err = _parse(request)
    if err:
        return err

    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()

    if not email or not password:
        return _json({'error': 'email and password are required'}, 400)

    try:
        participant = Participant.objects.get(email=email)
    except Participant.DoesNotExist:
        return _json({'error': 'Email not found. Please register.'}, 404)

    hashed = _hash_password(password)

    if participant.password == password:
        participant.password = hashed
        participant.save(update_fields=['password'])
    elif participant.password != hashed:
        return _json({'error': 'Incorrect password'}, 401)

    return _json({
        'participant_id': participant.id,
        'email': participant.email,
        'survey_done': participant.survey_done,
    })


# POST /api/forgot-password/
@csrf_exempt
def forgot_password(request):
    if request.method != 'POST':
        return _json({'error': 'POST required'}, 405)
    data, err = _parse(request)
    if err:
        return err

    email = data.get('email', '').strip().lower()
    if not email:
        return _json({'error': 'Email is required'}, 400)

    try:
        participant = Participant.objects.get(email=email)
    except Participant.DoesNotExist:
        return _json({'error': 'Email not found. Please register.'}, 404)

    temp_password = _generate_temp_password()
    participant.password = _hash_password(temp_password)
    participant.save(update_fields=['password'])

    return _json({
        'status': 'reset',
        'temp_password': temp_password,
        'message': 'Use this temporary password to login. Change it after login.',
    })


# POST /api/change-password/
@csrf_exempt
def change_password(request):
    if request.method != 'POST':
        return _json({'error': 'POST required'}, 405)
    data, err = _parse(request)
    if err:
        return err

    participant_id = data.get('participant_id')
    old_password = data.get('old_password', '').strip()
    new_password = data.get('new_password', '').strip()

    if not all([participant_id, old_password, new_password]):
        return _json({'error': 'Missing required fields'}, 400)
    if len(new_password) < 6:
        return _json({'error': 'New password must be at least 6 characters'}, 400)

    try:
        participant = Participant.objects.get(id=participant_id)
    except Participant.DoesNotExist:
        return _json({'error': 'Participant not found'}, 404)

    if participant.password != _hash_password(old_password):
        return _json({'error': 'Incorrect current password'}, 401)

    participant.password = _hash_password(new_password)
    participant.save(update_fields=['password'])

    return _json({'status': 'changed', 'message': 'Password changed successfully'})


# POST /api/survey/
@csrf_exempt
def submit_survey(request):
    if request.method != 'POST':
        return _json({'error': 'POST required'}, 405)
    data, err = _parse(request)
    if err:
        return err
    try:
        participant = Participant.objects.get(id=data.get('participant_id'))
    except Participant.DoesNotExist:
        return _json({'error': 'Participant not found'}, 404)
    if participant.survey_done:
        return _json({'status': 'already_submitted'})
    ParticipantSurvey.objects.update_or_create(
        participant=participant,
        defaults={
            'age': data.get('age', 0),
            'gender': data.get('gender', ''),
            'handedness': data.get('handedness', 'right'),
            'native_language': data.get('native_language', ''),
            'hometown': data.get('hometown', ''),
            'mother_tongue': data.get('mother_tongue', ''),
            'education_level': data.get('education_level', ''),
            'region': data.get('region', ''),
            'writing_fluency': data.get('writing_fluency', ''),
            'reading_fluency': data.get('reading_fluency', ''),
        },
    )
    participant.survey_done = True
    participant.save(update_fields=['survey_done'])
    return _json({'status': 'saved'})


# GET /api/progress/<participant_id>/
def get_progress(request, participant_id):
    if request.method != 'GET':
        return _json({'error': 'GET required'}, 405)
    try:
        participant = Participant.objects.get(id=participant_id)
    except Participant.DoesNotExist:
        return _json({'error': 'Participant not found'}, 404)

    done = set(
        HandwritingSample.objects.filter(participant=participant)
        .values_list('task', 'character')
    )
    total = sum(len(v) for v in TASK_CHARACTERS.values())

    for task in TASK_ORDER:
        for idx, char in enumerate(TASK_CHARACTERS[task]):
            if (task, char) not in done:
                return _json({
                    'all_done': False,
                    'next_task': task,
                    'next_char_index': idx,
                    'completed_count': len(done),
                    'total_count': total,
                })

    return _json({'all_done': True, 'completed_count': len(done), 'total_count': total})


# GET /api/progress/<participant_id>/<task>/
def get_task_progress(request, participant_id, task):
    if request.method != 'GET':
        return _json({'error': 'GET required'}, 405)
    try:
        participant = Participant.objects.get(id=participant_id)
    except Participant.DoesNotExist:
        return _json({'error': 'Participant not found'}, 404)

    if task not in TASK_CHARACTERS:
        return _json({'error': f'Unknown task: {task}'}, 400)

    done = set(
        HandwritingSample.objects.filter(participant=participant, task=task)
        .values_list('character', flat=True)
    )

    characters = TASK_CHARACTERS[task]
    for idx, char in enumerate(characters):
        if char not in done:
            return _json({
                'task': task,
                'next_char_index': idx,
                'completed_count': len(done),
                'total_count': len(characters),
                'all_done': False,
            })

    return _json({
        'task': task,
        'next_char_index': len(characters),
        'completed_count': len(done),
        'total_count': len(characters),
        'all_done': True,
    })


# POST /api/upload-writing/
@csrf_exempt
def upload_writing(request):
    if request.method != 'POST':
        return _json({'error': 'POST required'}, 405)
    data, err = _parse(request)
    if err:
        return err

    participant_id = data.get('participant_id')
    task = data.get('task', '').strip()
    character = data.get('character', '').strip()
    stroke_data = data.get('stroke_data')
    time_taken = data.get('time_taken')
    image_data = data.get('image')

    if not all([participant_id, task, character, stroke_data, time_taken]):
        return _json({'error': 'Missing required fields'}, 400)
    if task not in TASK_CHARACTERS:
        return _json({'error': f'Unknown task: {task}'}, 400)
    if character not in TASK_CHARACTERS.get(task, []):
        return _json({'error': f"Character '{character}' not valid for task '{task}'"}, 400)
    if not isinstance(stroke_data, list) or len(stroke_data) < 1:
        return _json({'error': 'stroke_data must be a non-empty list'}, 400)
    total_points = sum(len(s) for s in stroke_data if isinstance(s, list))
    if total_points < 5:
        return _json({'error': 'Too few stroke points'}, 400)

    try:
        participant = Participant.objects.get(id=participant_id)
    except Participant.DoesNotExist:
        return _json({'error': 'Participant not found'}, 404)

    if HandwritingSample.objects.filter(
        participant=participant, task=task, character=character
    ).exists():
        return _json({'error': 'Already submitted', 'status': 'duplicate'}, 409)

    try:
        sample = HandwritingSample.objects.create(
            participant=participant,
            task=task,
            character=character,
            stroke_data=stroke_data,
            time_taken=time_taken,
        )
    except IntegrityError:
        return _json({'error': 'Already submitted', 'status': 'duplicate'}, 409)

    if image_data:
        try:
            if 'base64,' not in image_data:
                return _json({'error': 'Invalid image format'}, 400)

            format, imgstr = image_data.split(';base64,')
            ext = format.split('/')[-1]

            decoded_file = base64.b64decode(imgstr)

            chars = TASK_CHARACTERS.get(task, [])
            try:
                char_index = chars.index(character) + TASK_OFFSETS.get(task, 1)
            except ValueError:
                char_index = 0

            file_name = f"{char_index}_{participant.id}.{ext}"

            sample.image.save(file_name, ContentFile(decoded_file), save=True)

            print("IMAGE SAVED:", sample.image.url)

        except Exception as e:
            print("IMAGE ERROR:", str(e))
            return _json({'error': 'Image save failed'}, 500)

    else:
        print(f'[WARN] No image data received for {character}')

    return _json({'status': 'saved', 'id': sample.id}, 201)


# POST /api/send-otp/
@csrf_exempt
def send_otp(request):
    if request.method != 'POST':
        return _json({'error': 'POST required'}, 405)
    data, err = _parse(request)
    if err:
        return err

    email = data.get('email', '').strip().lower()
    if not email:
        return _json({'error': 'Email is required'}, 400)

    try:
        participant = Participant.objects.get(email=email)
    except Participant.DoesNotExist:
        return _json({'error': 'Email not found. Please register.'}, 404)

    OTPCode.objects.filter(email=email, is_used=False).update(is_used=True)

    code = f"{random.randint(100000, 999999)}"
    OTPCode.objects.create(email=email, code=code)

    html_message = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin:0; padding:0; background-color:#f5efe6; font-family: Arial, sans-serif;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f5efe6; padding: 40px 0;">
            <tr>
                <td align="center">
                    <table width="480" cellpadding="0" cellspacing="0" style="background-color:#ffffff; border-radius:16px; overflow:hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">

                        <!-- Header -->
                        <tr>
                            <td align="center" style="background-color:#e67e22; padding: 32px 24px;">
                                <h1 style="margin:0; color:#ffffff; font-size:28px; letter-spacing:2px;">ಅಕ್ಷರ</h1>
                                <p style="margin:6px 0 0 0; color:#fde8d0; font-size:14px; letter-spacing:1px;">AKSHARA</p>
                                <p style="margin:4px 0 0 0; color:#fde8d0; font-size:12px;">Kannada Handwriting Research Project</p>
                            </td>
                        </tr>

                        <!-- Body -->
                        <tr>
                            <td style="padding: 36px 32px 24px 32px;">
                                <h2 style="margin:0 0 8px 0; color:#2c2c2c; font-size:20px;">Password Reset Request</h2>
                                <p style="margin:0 0 24px 0; color:#666666; font-size:14px; line-height:1.6;">
                                    We received a request to reset your password for your Akshara account.
                                    Use the OTP below to proceed.
                                </p>

                                <!-- OTP Box -->
                                <table width="100%" cellpadding="0" cellspacing="0">
                                    <tr>
                                        <td align="center" style="background-color:#fff4e8; border: 2px dashed #e67e22; border-radius:12px; padding: 28px 24px;">
                                            <p style="margin:0 0 8px 0; color:#e67e22; font-size:12px; font-weight:bold; letter-spacing:2px; text-transform:uppercase;">Your OTP Code</p>
                                            <p style="margin:0; color:#2c2c2c; font-size:42px; font-weight:bold; letter-spacing:10px;">{code}</p>
                                            <p style="margin:10px 0 0 0; color:#999999; font-size:12px;">Valid for 10 minutes only</p>
                                        </td>
                                    </tr>
                                </table>

                                <p style="margin:24px 0 0 0; color:#666666; font-size:13px; line-height:1.6;">
                                    Enter this code in the app to reset your password.
                                    If you did not request this, please ignore this email — your account is safe.
                                </p>
                            </td>
                        </tr>

                        <!-- Divider -->
                        <tr>
                            <td style="padding: 0 32px;">
                                <hr style="border:none; border-top:1px solid #f0e6d6; margin:0;">
                            </td>
                        </tr>

                        <!-- Footer -->
                        <tr>
                            <td align="center" style="padding: 20px 32px 28px 32px;">
                                <p style="margin:0; color:#aaaaaa; font-size:12px;">
                                    © 2025 Akshara — Kannada Handwriting Research Project
                                </p>
                                <p style="margin:4px 0 0 0; color:#aaaaaa; font-size:11px;">
                                    This is an automated email. Please do not reply.
                                </p>
                            </td>
                        </tr>

                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

    plain_message = f'Your Akshara OTP for password reset is: {code}\n\nThis code expires in 10 minutes.\n\nIf you did not request this, ignore this email.'

    try:
        msg = EmailMultiAlternatives(
            subject='🔐 Your Akshara Password Reset OTP',
            body=plain_message,
            from_email=f'Akshara Project <{settings.EMAIL_HOST_USER}>',
            to=[email],
        )
        msg.attach_alternative(html_message, "text/html")
        msg.send()
    except Exception as e:
        return _json({'error': f'Failed to send email: {str(e)}'}, 500)

    return _json({'status': 'sent', 'message': 'OTP sent to your email'})


# POST /api/verify-otp-reset/
@csrf_exempt
def verify_otp_reset(request):
    if request.method != 'POST':
        return _json({'error': 'POST required'}, 405)
    data, err = _parse(request)
    if err:
        return err

    email = data.get('email', '').strip().lower()
    code = data.get('code', '').strip()
    new_password = data.get('new_password', '').strip()

    if not all([email, code, new_password]):
        return _json({'error': 'Missing required fields'}, 400)
    if len(new_password) < 6:
        return _json({'error': 'Password must be at least 6 characters'}, 400)

    otp = OTPCode.objects.filter(
        email=email, code=code, is_used=False
    ).order_by('-created_at').first()

    if not otp:
        return _json({'error': 'Invalid OTP. Please try again.'}, 400)
    if otp.is_expired():
        otp.is_used = True
        otp.save()
        return _json({'error': 'OTP expired. Please request a new one.'}, 400)

    try:
        participant = Participant.objects.get(email=email)
    except Participant.DoesNotExist:
        return _json({'error': 'Email not found.'}, 404)

    participant.password = _hash_password(new_password)
    participant.save(update_fields=['password'])

    otp.is_used = True
    otp.save()

    return _json({'status': 'reset', 'message': 'Password reset successfully'})