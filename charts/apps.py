from django.apps import AppConfig


class ChartsConfig(AppConfig):
    name = 'charts'

    def ready(self):
        from . import title_credits  # noqa: F401
