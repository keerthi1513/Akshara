from django.urls import path
from .views import (
    register, login, submit_survey, get_progress, get_task_progress,
    upload_writing, forgot_password, change_password,
    send_otp, verify_otp_reset,
)

urlpatterns = [
    path('register/', register),
    path('login/', login),
    path('survey/', submit_survey),
    path('progress/<int:participant_id>/', get_progress),
    path('progress/<int:participant_id>/<str:task>/', get_task_progress),
    path('upload-writing/', upload_writing),
    path('forgot-password/', forgot_password),
    path('change-password/', change_password),
    path('send-otp/', send_otp),
    path('verify-otp-reset/', verify_otp_reset),
]