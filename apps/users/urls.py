from django.urls import path
from apps.users.view.users import UserInfoLoginView, UserListView,UpdateUserView,DeleteUserView,CreateUserInfoView
urlpatterns = [
    path('login/', UserInfoLoginView.as_view()),
    path('create/', CreateUserInfoView.as_view()),
    path('list/', UserListView.as_view()),
    path('update/', UpdateUserView.as_view()),
    path('delete/', DeleteUserView.as_view())
]