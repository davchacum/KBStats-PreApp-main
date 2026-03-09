from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = 'Seed initial users: superadmin (superuser), admin (staff), usuario (normal)'

    def handle(self, *args, **options):
        User = get_user_model()

        users = [
            {
                'username': 'superadmin',
                'email': 'superadmin@example.com',
                'password': 'superadminpass',
                'is_superuser': True,
                'is_staff': True,
            },
            {
                'username': 'admin',
                'email': 'admin@example.com',
                'password': 'adminpass',
                'is_superuser': False,
                'is_staff': True,
            },
            {
                'username': 'usuario',
                'email': 'usuario@example.com',
                'password': 'userpass',
                'is_superuser': False,
                'is_staff': False,
            },
        ]

        for u in users:
            username = u['username']
            if User.objects.filter(username=username).exists():
                self.stdout.write(self.style.WARNING(f"Usuario '{username}' ya existe. Omitiendo."))
                continue

            if u['is_superuser']:
                User.objects.create_superuser(username=u['username'], email=u['email'], password=u['password'])
                self.stdout.write(self.style.SUCCESS(f"Superusuario '{username}' creado."))
            else:
                user = User.objects.create_user(username=u['username'], email=u['email'], password=u['password'])
                user.is_staff = u['is_staff']
                user.save()
                self.stdout.write(self.style.SUCCESS(f"Usuario '{username}' creado (staff={user.is_staff})."))

        self.stdout.write(self.style.NOTICE('Seed de usuarios completado.'))
