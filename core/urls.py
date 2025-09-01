# core/urls.py - This file you already created
# This handles all the specific functionality within your core app

from django.urls import path
from . import views

app_name = 'core'  # This creates a namespace for your URLs

urlpatterns = [
    # Main pages
    path('', views.home, name='home'),  # URL: /
    path('mps/', views.mp_list, name='mp_list'),  # URL: /mps/
    path('mps/<int:mp_id>/', views.mp_detail, name='mp_detail'),  # URL: /mps/123/
    path('votes/', views.vote_list, name='vote_list'),  # URL: /votes/
    path('votes/<int:vote_id>/', views.vote_detail, name='vote_detail'),  # URL: /votes/456/
    path('compare/', views.compare_mps, name='compare_mps'),  # URL: /compare/

    # API endpoints
    path('api/mp-search/', views.api_mp_search, name='api_mp_search'),  # URL: /api/mp-search/
    path('api/vote-search/', views.api_vote_search, name='api_vote_search'),  # URL: /api/vote-search/
]