[app]
title = Music Downloader
package.name = musicdownloader
package.domain = org.musicapp

source.dir = .
source.include_exts = py,png,jpg,kv,atlas
source.exclude_dirs = .github,bin,.buildozer

version = 0.1

requirements = python3,kivy==2.3.0,openssl,certifi,yt-dlp,pyjnius,android

orientation = portrait
fullscreen = 0

android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,READ_MEDIA_AUDIO,READ_MEDIA_VIDEO
android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
