import os
from decouple import config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SECRET_KEY = "dwsdfasdfasdfa23314wesvc#a3adf%6-secret-key"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "fastadmin",
    "admin",
    "admin.db",
]

DB_PASSWORD = config("DB_PASSWORD")
DB_HOST = config("DB_HOST")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "postgres",
        "USER": "postgres.whfububdcpttgxivvtvi",
        "PASSWORD": DB_PASSWORD,
        "HOST": DB_HOST,
        "PORT": "6543",
        "OPTIONS": {
            "sslmode": "require",
        },
    }
}

# Needed if not using Django project
USE_TZ = True

TINYMCE_JS_URL = "https://cdn.tiny.cloud/1/no-api-key/tinymce/6/tinymce.min.js"

TINYMCE_COMPRESSOR = False


TINYMCE_DEFAULT_CONFIG = {
    "theme": "silver",
    "resize": "false",
    "menubar": "file edit view insert format tools table help",
    "toolbar": "undo redo | bold italic underline strikethrough | fontselect fontsizeselect formatselect | alignleft aligncenter alignright alignjustify | outdent indent |  numlist bullist checklist | forecolor backcolor casechange permanentpen formatpainter removeformat | pagebreak | charmap emoticons | fullscreen  preview save print | insertfile image media pageembed template link anchor codesample | a11ycheck ltr rtl | showcomments addcomment code typography",
    "plugins": "advlist autolink lists link image charmap print preview anchor searchreplace visualblocks code fullscreen insertdatetime media table powerpaste advcode help wordcount spellchecker typography",
    "selector": "textarea",
}
