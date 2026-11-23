#!/usr/bin/env python
# -*- coding：utf-8 -*-
"""

@Time   : 2025/11/25 20:23
@Author : sunxiaojie
@File   : gaode_weather.py
"""
import json
import os

import requests
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from internal.config.settings import get_settings


class GaodeWeatherArgsSchema(BaseModel):
    city: str = Field(description="需要查询天气预报的目标城市，例如：深圳")


@tool(args_schema=GaodeWeatherArgsSchema)
def gaode_weather(city: str) -> str:
    """根据传入的城市名查询天气。当你想查询天气或者与天气相关的问题时可以使用的工具。"""

    try:
        gaode_api_key = os.getenv("GAODE_API_KEY")
        if not gaode_api_key:
            return "高德开发平台API未配置"

        api_domain = get_settings().gaode_api_domain
        session = requests.session()

        city_url = f"{api_domain}/config/district?key={gaode_api_key}&keywords={city}&subdistrict=0"
        city_response = session.get(city_url, headers={"Content-Type": "application/json; charset=utf-8"})
        city_response.raise_for_status()
        city_data = city_response.json()

        if city_data.get("info") == "OK" and city_data.get("districts"):
            ad_code = city_data["districts"][0]["adcode"]

            weather_url = f"{api_domain}/weather/weatherInfo?key={gaode_api_key}&city={ad_code}"
            weather_response = session.get(weather_url, headers={"Content-Type": "application/json; charset=utf-8"})
            weather_response.raise_for_status()
            weather_data = weather_response.json()

            if weather_data.get("info") == "OK":
                return json.dumps(weather_data, ensure_ascii=False)

        return f"未找到城市 {city} 的天气信息"

    except Exception as e:
        return f"获取 {city} 天气预报信息失败: {e!s}"
