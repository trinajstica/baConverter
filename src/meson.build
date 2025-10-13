project_sources = files('main.c')

adwaita_dep = dependency('libadwaita-1')
gtk_dep = dependency('gtk4')
json_dep = dependency('json-glib-1.0')

exe = executable('bac',
  project_sources,
  include_directories: include_directories('.'),
  dependencies: [adwaita_dep, gtk_dep, json_dep],
  install: true)

# Install desktop file
desktop_file = files('../data/si.generacija.baconvert.desktop')
install_data(desktop_file, install_dir: join_paths(get_option('datadir'), 'applications'))

# Install icon (scalable svg)
icon_file = files('../data/icons/hicolor/scalable/apps/baConvert.svg')
install_data(icon_file, install_dir: join_paths(get_option('datadir'), 'icons', 'hicolor', 'scalable', 'apps'))

# Install symbolic icon (monochrome) for desktop themes
symbolic_icon_file = files('../data/icons/hicolor/symbolic/apps/baConvert-symbolic.svg')
install_data(symbolic_icon_file, install_dir: join_paths(get_option('datadir'), 'icons', 'hicolor', 'symbolic', 'apps'))

# Install generated from-user variants
icon_from_user = files('../data/icons/hicolor/scalable/apps/baConvert-from-user.svg')
install_data(icon_from_user, install_dir: join_paths(get_option('datadir'), 'icons', 'hicolor', 'scalable', 'apps'))
symbolic_from_user = files('../data/icons/hicolor/symbolic/apps/baConvert-symbolic-from-user.svg')
install_data(symbolic_from_user, install_dir: join_paths(get_option('datadir'), 'icons', 'hicolor', 'symbolic', 'apps'))
