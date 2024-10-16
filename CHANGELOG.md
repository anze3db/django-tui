# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Calendar Versioning](https://calver.org).

## [24.4] - 2024-10-16

### Fixed

Crash when pressing the down key. Thank you @ALERTua!

## [24.3] - 2024-07-05

### Added

Command highlighting on Python 3.12
Django 5.1 support

### Fixed

Crash on startup when used with older Textual versions
Bug that prevented commands from working


## [24.2] - 2024-03-29

### Fixed

Regression caused by Textual 0.54.0 release.

## [24.1] - 2024-01-18

### Added

Improvements to copying shell input and output. Thanks @shtayeb!


## [23.9] - 2023-12-19

### Added

Interactive Shell screen for running ORM queries.

https://github.com/anze3db/django-tui/assets/513444/8a056da8-85a8-4086-9fa8-433b7346e787

## [23.8] - 2023-12-15

### Fixed

Copy to clipboard button not working on Windows. Thank you @shtayeb!

## [23.7] - 2023-12-04

### Added

Python 3.12 support

## [23.6] - 2023-10-24

### Added

Ability to copy the command to the clipboard.

### Changed

Development Status classifier was changed from Beta to Production/Stable.


## [23.5] - 2023-08-27

Change accent colors to Django green

### Added

- Django color theme

## [23.4] - 2023-08-24

README improvements

### Added

- Screenshot at the top of the README
- Better install instructions

## [23.3] - 2023-08-23

Added video demo to the project description 🎉

### Added

- Video Demo

## [23.2] - 2023-08-23

Add about screen.

### Added

- About screen

## [23.1] - 2023-08-23

Fix crash on startup.

### Fixed

- Crash when a command module doesn't have a `Command` class.




## [23.0] - 2023-08-23

Initial Release!
