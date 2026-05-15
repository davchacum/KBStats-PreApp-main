import random
import string
from django.shortcuts import render, redirect


def index(request):
    return render(request, 'Kblix/index.html')


def sala(request, room_id):
    return render(request, 'Kblix/sala.html', {'room_id': room_id})


def crear_sala(request):
    room_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return redirect('kblix:sala', room_id=room_id)
