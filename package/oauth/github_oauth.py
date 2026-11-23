#!/usr/bin/env python
"""
@Time    : 2025/12/20 23:27
@Author  : sunxiaojie
@File    : github_oauth.py
"""
import urllib.parse

import requests

from internal.config.settings import get_settings

from .oauth import OAuth, OAuthUserInfo


class GithubOAuth(OAuth):
    """GithubOAuth第三方授权认证类"""

    # 以下端点经系统设置（settings.py / .env）惰性读取，支持 GitHub Enterprise 私有化部署

    @property
    def _authorize_url(self) -> str:
        return f"{get_settings().github_oauth_base_url}/login/oauth/authorize"  # 跳转授权接口

    @property
    def _access_token_url(self) -> str:
        return f"{get_settings().github_oauth_base_url}/login/oauth/access_token"  # 跳转授权令牌接口

    @property
    def _user_info_url(self) -> str:
        return f"{get_settings().github_api_base_url}/user"  # 获取用户信息接口

    @property
    def _email_info_url(self) -> str:
        return f"{get_settings().github_api_base_url}/user/emails"  # 获取用户邮箱接口

    def get_provider(self) -> str:
        return "github"

    def get_authorization_url(self) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": "user:email",  # 只请求用户基本信息
        }
        return f"{self._authorize_url}?{urllib.parse.urlencode(params)}"

    def get_access_token(self, code: str) -> str:
        # 1、组装请求数据
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        headers = {"Accept": "application/json"}

        # 2、发起post请求并获取相应数据
        resp = requests.post(self._access_token_url, data=data, headers=headers)
        resp.raise_for_status()
        resp_json = resp.json()

        # 3、提取access_token对应的数据
        access_token = resp_json.get("access_token")
        if not access_token:
            raise ValueError(f"Github OAuth授权失败：{resp_json}")

        return access_token

    def get_raw_user_info(self, token: str) -> dict:
        # 1、组装请求数据
        headers = {"Authorization": f"token {token}"}

        # 2、发起get请求获取用户数据
        resp = requests.get(self._user_info_url, headers=headers)
        resp.raise_for_status()
        raw_info = resp.json()

        # 3、发起get请求获取用户邮箱
        email_resp = requests.get(self._email_info_url, headers=headers)
        email_resp.raise_for_status()
        email_info = email_resp.json()

        # 4、提取邮箱数据
        primary_email = next((email for email in email_info if email.get("primary", None)), None)

        return {**raw_info, "email": primary_email.get("email", None)}

    def _transform_user_info(self, raw_info: dict) -> OAuthUserInfo:
        email = raw_info.get("email")
        if not email:
            email = f"{raw_info.get('id')}+{raw_info.get('login')}@user.no-reply@github.com"

        return OAuthUserInfo(
            id=str(raw_info.get("id")),
            name=str(raw_info.get("name")),
            email=str(email),
        )
