from django.urls import path

from apps.core import views

app_name = 'core'

urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),
    path('saude/banco/', views.saude_banco, name='saude_banco'),
]
