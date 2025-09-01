# democrasee/urls.py - This is your main project URL file
# This connects everything together and routes traffic to the right apps

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    # Admin interface - handles all /admin/ URLs
    path('admin/', admin.site.urls),
    
    # Core app - handles all main website URLs
    # The '' means "root level" - so all core URLs start from the domain root
    path('', include('core.urls')),
    
    # If you add more apps later, you might have:
    # path('api/v2/', include('api.urls')),        # For a separate API app
    # path('blog/', include('blog.urls')),         # For a blog app
    # path('accounts/', include('accounts.urls')), # For user authentication
]

# What this means:
# - /admin/ -> goes to Django admin
# - / -> goes to core.views.home (your homepage)
# - /mps/ -> goes to core.views.mp_list
# - /votes/123/ -> goes to core.views.vote_detail with vote_id=123
# etc.