#include "duckdb_extension.h"
#include <iostream>
#include <string>
#include <cstdio>
#include <cstdlib>
#include <cstring>

DUCKDB_EXTENSION_EXTERN

void RegisterLemmaFunction(duckdb_connection connection);

static bool lemma_demo_mode() {
    const char* v = std::getenv("LEMMA_DEMO");
    return v != nullptr && v[0] != '\0' && std::strcmp(v, "0") != 0 && std::strcmp(v, "false") != 0
           && std::strcmp(v, "False") != 0;
}

static void LemmaOptimize(duckdb_function_info info, duckdb_data_chunk input, duckdb_vector output) {
    idx_t input_size = duckdb_data_chunk_get_size(input);
    duckdb_vector query_vec = duckdb_data_chunk_get_vector(input, 0);
    duckdb_string_t* query_data = (duckdb_string_t*)duckdb_vector_get_data(query_vec);

    for (idx_t row = 0; row < input_size; row++) {
        uint32_t length = duckdb_string_t_length(query_data[row]);
        const char* data_ptr = duckdb_string_t_data(&query_data[row]);
        std::string query_str(data_ptr, length);

        const std::string temp_sql_path = "db_extension/temp_query.sql";
        FILE* sql_file = fopen(temp_sql_path.c_str(), "w");
        if (sql_file) {
            fwrite(query_str.c_str(), 1, query_str.length(), sql_file);
            fclose(sql_file);
        }

        // Demo progress UI → Python stderr (streams live). Query result scalar → stdout (captured for DuckDB box).
        std::string cmd =
            "PYTHONUNBUFFERED=1 uv run python -m db_extension.run_optimizer --file " + temp_sql_path;

        char buffer[1024];
        FILE* pipe = popen(cmd.c_str(), "r");
        int exit_code = -1;
        std::string captured;
        const bool demo = lemma_demo_mode();
        if (pipe) {
            while (fgets(buffer, sizeof(buffer), pipe) != nullptr) {
                captured += buffer;
                if (!demo) {
                    std::cout << buffer << std::flush;
                }
            }
            exit_code = pclose(pipe);
            while (!captured.empty() && (captured.back() == '\n' || captured.back() == '\r')) {
                captured.pop_back();
            }
        }

        remove(temp_sql_path.c_str());

        std::string output_str;
        if (exit_code == 0) {
            output_str = demo ? captured : "";
        } else {
            output_str = demo ? ("Lemma optimization failed.\n" + captured) : "Lemma optimization failed.";
        }
        duckdb_vector_assign_string_element(output, row, output_str.c_str());
    }
}

void RegisterLemmaFunction(duckdb_connection connection) {
    duckdb_scalar_function function = duckdb_create_scalar_function();
    duckdb_scalar_function_set_name(function, "lemma_optimize");

    duckdb_logical_type param_type = duckdb_create_logical_type(DUCKDB_TYPE_VARCHAR);
    duckdb_scalar_function_add_parameter(function, param_type);

    duckdb_logical_type ret_type = duckdb_create_logical_type(DUCKDB_TYPE_VARCHAR);
    duckdb_scalar_function_set_return_type(function, ret_type);

    duckdb_destroy_logical_type(&param_type);
    duckdb_destroy_logical_type(&ret_type);

    duckdb_scalar_function_set_function(function, LemmaOptimize);

    duckdb_register_scalar_function(connection, function);
    duckdb_destroy_scalar_function(&function);

    duckdb_scalar_function function_alias = duckdb_create_scalar_function();
    duckdb_scalar_function_set_name(function_alias, "lemma");

    param_type = duckdb_create_logical_type(DUCKDB_TYPE_VARCHAR);
    duckdb_scalar_function_add_parameter(function_alias, param_type);

    ret_type = duckdb_create_logical_type(DUCKDB_TYPE_VARCHAR);
    duckdb_scalar_function_set_return_type(function_alias, ret_type);

    duckdb_destroy_logical_type(&param_type);
    duckdb_destroy_logical_type(&ret_type);

    duckdb_scalar_function_set_function(function_alias, LemmaOptimize);

    duckdb_register_scalar_function(connection, function_alias);
    duckdb_destroy_scalar_function(&function_alias);
}

DUCKDB_EXTENSION_ENTRYPOINT(duckdb_connection connection, duckdb_extension_info info, struct duckdb_extension_access *access) {
    RegisterLemmaFunction(connection);
    return true;
}
