cmake_minimum_required(VERSION 3.5)

set(TARGET_NAME lemma)
set(EXTENSION_NAME ${TARGET_NAME}_extension)
set(LOADABLE_EXTENSION_NAME ${TARGET_NAME}_loadable_extension)

project(${TARGET_NAME})

# C++11, the standard DuckDB itself is built with (its CMakeLists sets it for every target in the build).

include_directories(src/include)

set(EXTENSION_SOURCES src/lemma_extension.cpp src/lemma_util.cpp)

build_static_extension(${TARGET_NAME} ${EXTENSION_SOURCES})
build_loadable_extension(${TARGET_NAME} " " ${EXTENSION_SOURCES})

# dlopen of the cached verified libraries
target_link_libraries(${EXTENSION_NAME} ${CMAKE_DL_LIBS})
target_link_libraries(${LOADABLE_EXTENSION_NAME} ${CMAKE_DL_LIBS})

install(
  TARGETS ${EXTENSION_NAME}
  EXPORT "${DUCKDB_EXPORT_SET}"
  LIBRARY DESTINATION "${INSTALL_LIB_DIR}"
  ARCHIVE DESTINATION "${INSTALL_LIB_DIR}")
