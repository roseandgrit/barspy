from setuptools import setup

APP = ['barspy.py']
OPTIONS = {
    'argv_emulation': False,
    'iconfile': 'assets/BarSpy.icns',
    'plist': {
        'CFBundleName': 'Bar Spy',
        'CFBundleDisplayName': 'Bar Spy',
        'CFBundleIdentifier': 'com.roseandgrit.barspy',
        'CFBundleVersion': '2.0',
        'CFBundleShortVersionString': '2.0',
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
