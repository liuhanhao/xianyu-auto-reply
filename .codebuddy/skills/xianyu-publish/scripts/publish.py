#!/usr/bin/env python3
"""读取商品配置文件，通过 xianyu-auto-reply 公开接口发布闲鱼商品。

用法:
    python3 publish.py <config.yaml>             # 发布商品
    python3 publish.py <config.yaml> --dry-run   # 只预览分类与图片，不发布
    python3 publish.py <config.yaml> --accounts  # 只列出秘钥下的可用账号

前置条件:
    xianyu-auto-reply 的 backend-web 服务运行中（默认 http://127.0.0.1:8089），
    目标闲鱼账号已登录且 Cookie 有效。
"""
from __future__ import annotations

import argparse
import mimetypes
import sys
from pathlib import Path

import requests
import yaml

BASE = "http://127.0.0.1:8089/api/v1"
TIMEOUT = 120

# 分类推荐结果字段 -> 发布接口字段
CATEGORY_FIELDS = {
    "cat_id": "platform_category_id",
    "cat_name": "platform_category_name",
    "channel_cat_id": "platform_channel_category_id",
    "channel_cat_name": "platform_channel_category_name",
    "leaf_id": "platform_leaf_id",
    "tb_cat_id": "platform_tb_category_id",
}


def fail(message: str) -> None:
    print(f"错误：{message}", file=sys.stderr)
    raise SystemExit(1)


def call(path: str, body: dict | None = None, form: dict | None = None, files: dict | None = None) -> dict:
    """调用公开接口，HTTP 恒为 200，业务状态放在 success 和 code 字段。"""
    try:
        resp = requests.post(f"{BASE}{path}", json=body, data=form, files=files, timeout=TIMEOUT)
    except requests.RequestException as exc:
        fail(f"无法连接 {BASE}{path}：{exc}。请确认 backend-web 服务在运行")
    try:
        payload = resp.json()
    except ValueError:
        fail(f"{path} 返回非 JSON：HTTP {resp.status_code} {resp.text[:200]}")
    if not payload.get("success"):
        fail(f"{path} 失败 [code={payload.get('code')}]：{payload.get('message')}")
    return payload.get("data") or {}


def list_accounts(secret_key: str) -> list[dict]:
    return call("/external/enabled-accounts", body={"secret_key": secret_key}).get("accounts") or []


def recommend_category(secret_key: str, account_id: str, description: str) -> list[dict]:
    data = call(
        "/external/category/recommend",
        body={"secret_key": secret_key, "account_id": account_id, "description": description},
    )
    return data.get("candidates") or []


def upload_image(secret_key: str, account_id: str, path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    with path.open("rb") as handle:
        files = {"file": (path.name, handle, mime)}
        form = {"secret_key": secret_key, "account_id": account_id, "media_type": "image"}
        return call("/external/publish/media", form=form, files=files)["media_id"]


def resolve_images(raw_images: list[str], base_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for raw in raw_images or []:
        text = str(raw or "").strip()
        if not text:
            continue
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        if not path.is_file():
            fail(f"图片不存在：{path}")
        paths.append(path)
    if not paths:
        fail("images 至少需要一张本地图片路径")
    if len(paths) > 9:
        fail(f"images 最多 9 张，当前 {len(paths)} 张")
    return paths


def build_item(config: dict, candidate: dict, media_ids: list[str]) -> dict:
    item = {
        "title": str(config["title"]).strip(),
        "description": str(config["description"]).strip(),
        "price": float(config["price"]),
        "address": str(config["address"]).strip(),
        "image_media_ids": media_ids,
        "quantity": int(config.get("quantity") or 1),
        "shipping_method": str(config.get("shipping_method") or "free").strip(),
        "postage": float(config.get("postage") or 0),
    }
    if config.get("original_price"):
        item["original_price"] = float(config["original_price"])
    for source, target in CATEGORY_FIELDS.items():
        if candidate.get(source):
            item[target] = candidate[source]
    return item


def print_candidates(candidates: list[dict], chosen_index: int) -> None:
    print(f"分类推荐结果（共 {len(candidates)} 个，当前选用 # {chosen_index}）：")
    for index, candidate in enumerate(candidates):
        mark = "*" if index == chosen_index else " "
        path = " > ".join(step.get("name", "") for step in candidate.get("path") or [])
        print(f" {mark} [{index}] {path or candidate.get('cat_name') or '(未命名)'}")
    print()


def main() -> None:
    global BASE
    parser = argparse.ArgumentParser(description="按配置文件发布闲鱼商品")
    parser.add_argument("config", help="商品配置文件路径（YAML）")
    parser.add_argument("--dry-run", action="store_true", help="只预览分类与图片，不发布")
    parser.add_argument("--accounts", action="store_true", help="只列出秘钥下的可用账号")
    parser.add_argument("--base-url", default=BASE, help=f"backend-web 地址，默认 {BASE}")
    args = parser.parse_args()

    BASE = args.base_url.rstrip("/")

    config_path = Path(args.config).expanduser()
    if not config_path.is_file():
        fail(f"配置文件不存在：{config_path}")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    secret_key = str(config.get("secret_key") or "").strip()
    if not secret_key:
        fail("配置缺少 secret_key：请在客户端「个人设置」页的「分销秘钥」一栏复制后填入")

    if args.accounts:
        accounts = list_accounts(secret_key)
        if not accounts:
            fail("该秘钥下没有闲鱼账号，请先在客户端添加账号")
        for account in accounts:
            state = "启用" if account.get("enabled") else "禁用"
            print(f"  {account['account_id']}  [{state}]  {account.get('remark') or '(无备注)'}")
        return

    account_id = str(config.get("account_id") or "").strip()
    if not account_id:
        print("配置未指定 account_id，该秘钥下的账号：")
        for account in list_accounts(secret_key):
            print(f"  {account['account_id']}  {account.get('remark') or '(无备注)'}")
        fail("请把要发布的账号 ID 填入配置后重跑")

    for field in ("title", "description", "price", "address"):
        if not str(config.get(field) or "").strip():
            fail(f"配置缺少必填项：{field}")
    if float(config["price"]) <= 0:
        fail("price 必须大于 0")

    images = resolve_images(config.get("images"), config_path.parent)

    candidates = recommend_category(
        secret_key,
        account_id,
        f"{config['title']}\n{config['description']}".strip()[:1500],
    )
    if not candidates:
        fail("分类推荐未返回结果，请确认该账号 Cookie 有效")

    chosen_index = int(config.get("category_index") or 0)
    if not 0 <= chosen_index < len(candidates):
        fail(f"category_index={chosen_index} 超出范围，可用 0~{len(candidates) - 1}")
    candidate = candidates[chosen_index]
    print_candidates(candidates, chosen_index)

    media_ids = [upload_image(secret_key, account_id, path) for path in images]
    print(f"已上传 {len(media_ids)} 张图片")

    item = build_item(config, candidate, media_ids)

    if args.dry_run:
        print("预览（未发布）：")
        print(f"  账号    {account_id}")
        print(f"  标题    {item['title']}")
        print(f"  售价    {item['price']}")
        print(f"  所在地  {item['address']}")
        print(f"  分类    {item.get('platform_category_name') or '(未识别)'}")
        return

    result = call(
        "/external/publish/single",
        body={"secret_key": secret_key, "account_id": account_id, **item},
    )
    print("发布成功")
    print(f"  商品ID  {result.get('item_id')}")
    print(f"  链接    {result.get('item_url')}")
    print(f"  日志ID  {result.get('log_id')}")


if __name__ == "__main__":
    main()
