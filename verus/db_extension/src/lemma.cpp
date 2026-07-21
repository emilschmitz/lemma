#include "duckdb_extension.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>

DUCKDB_EXTENSION_EXTERN

void RegisterLemmaFunction(duckdb_connection connection);

static void LemmaExperiment(duckdb_function_info info, duckdb_data_chunk input, duckdb_vector output) {
    idx_t input_size = duckdb_data_chunk_get_size(input);
    duckdb_vector query_vec = duckdb_data_chunk_get_vector(input, 0);
    duckdb_string_t* query_data = (duckdb_string_t*)duckdb_vector_get_data(query_vec);

    for (idx_t row = 0; row < input_size; row++) {
        uint32_t length = duckdb_string_t_length(query_data[row]);
        const char* data_ptr = duckdb_string_t_data(&query_data[row]);
        std::string query_str(data_ptr, length);

        const std::string temp_sql_path = "verus/db_extension/temp_query.sql";
        FILE* sql_file = fopen(temp_sql_path.c_str(), "w");
        if (sql_file) {
            fwrite(query_str.c_str(), 1, query_str.length(), sql_file);
            fclose(sql_file);
        }

        std::string cmd =
            "PYTHONUNBUFFERED=1 uv run python -m verus.db_extension.run_experiment --file " + temp_sql_path;

        char buffer[1024];
        FILE* pipe = popen(cmd.c_str(), "r");
        int exit_code = -1;
        std::string captured;
        if (pipe) {
            while (fgets(buffer, sizeof(buffer), pipe) != nullptr) {
                captured += buffer;
            }
            exit_code = pclose(pipe);
            while (!captured.empty() && (captured.back() == '\n' || captured.back() == '\r')) {
                captured.pop_back();
            }
        }

        remove(temp_sql_path.c_str());

        std::string output_str;
        if (exit_code == 0) {
            output_str = captured;
        } else {
            output_str = "Lemma experiment failed.\n" + captured;
        }
        duckdb_vector_assign_string_element(output, row, output_str.c_str());
    }
}

static void LemmaExportTable(duckdb_function_info info, duckdb_data_chunk input, duckdb_vector output) {
    idx_t input_size = duckdb_data_chunk_get_size(input);
    duckdb_vector table_vec = duckdb_data_chunk_get_vector(input, 0);
    duckdb_string_t* table_data = (duckdb_string_t*)duckdb_vector_get_data(table_vec);

    for (idx_t row = 0; row < input_size; row++) {
        uint32_t length = duckdb_string_t_length(table_data[row]);
        const char* data_ptr = duckdb_string_t_data(&table_data[row]);
        std::string table_name(data_ptr, length);

        std::string cmd =
            "PYTHONUNBUFFERED=1 LEMMA_LOAD_FROM_DUCKDB=1 uv run python -c \""
            "import duckdb; from pathlib import Path; "
            "from verus.db_extension.duckdb_memory import export_table, default_export_dir; "
            "con=duckdb.connect(); "
            "m=export_table(con, '" +
            table_name + "', default_export_dir()); "
            "print('exported', m['row_count'], 'rows')\"";

        char buffer[1024];
        FILE* pipe = popen(cmd.c_str(), "r");
        std::string captured;
        if (pipe) {
            while (fgets(buffer, sizeof(buffer), pipe) != nullptr) {
                captured += buffer;
            }
            pclose(pipe);
        }
        duckdb_vector_assign_string_element(output, row, captured.c_str());
    }
}

static void register_varchar_scalar(
    duckdb_connection connection,
    const char* name,
    duckdb_scalar_function_t fn
) {
    duckdb_scalar_function function = duckdb_create_scalar_function();
    duckdb_scalar_function_set_name(function, name);
    duckdb_logical_type param_type = duckdb_create_logical_type(DUCKDB_TYPE_VARCHAR);
    duckdb_scalar_function_add_parameter(function, param_type);
    duckdb_logical_type ret_type = duckdb_create_logical_type(DUCKDB_TYPE_VARCHAR);
    duckdb_scalar_function_set_return_type(function, ret_type);
    duckdb_destroy_logical_type(&param_type);
    duckdb_destroy_logical_type(&ret_type);
    duckdb_scalar_function_set_function(function, fn);
    duckdb_register_scalar_function(connection, function);
    duckdb_destroy_scalar_function(&function);
}

void RegisterLemmaFunction(duckdb_connection connection) {
    register_varchar_scalar(connection, "lemma", LemmaExperiment);
    register_varchar_scalar(connection, "lemma_experiment", LemmaExperiment);
    register_varchar_scalar(connection, "lemma_export_table", LemmaExportTable);
}

DUCKDB_EXTENSION_ENTRYPOINT(duckdb_connection connection, duckdb_extension_info info, struct duckdb_extension_access *access) {
    RegisterLemmaFunction(connection);
    return true;
}
