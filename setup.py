from setuptools import setup

APP = ['kizwatch.py']
OPTIONS = {
    'argv_emulation': False,
    'plist': {
        'CFBundleName': 'KizWatch',
        'CFBundleDisplayName': 'KizWatch',
        'CFBundleIdentifier': 'com.roseandgrit.kizwatch',
        'CFBundleVersion': '1.0',
        'CFBundleShortVersionString': '1.0',
        'LSUIElement': True,
        'NSHighResolutionCapable': True,
    },
    'packages': ['rumps'],
}

setup(
    app=APP,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
