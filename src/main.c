#include <adwaita.h>
#include <gtk/gtk.h>
#include <glib/gstdio.h>
#include <json-glib/json-glib.h>
#include <sys/wait.h>
#include <signal.h>

static gchar *input_file = NULL;
static gchar *output_file = NULL;
static GtkWidget *input_label;
static GtkWidget *output_label;
static GtkWidget *copy_audio_check;
static GtkWidget *audio_combo;
static GtkWidget *copy_video_check;
static GtkWidget *video_combo;
static GtkWidget *format_combo_audio;
static GtkStringList *audio_model = NULL;
static GtkStringList *video_model = NULL;
static GtkStringList *format_model = NULL;
static GtkWidget *start_button;
static GtkWidget *stop_button;
static GtkWidget *reset_audio;
static GtkWidget *reset_video;
static GtkWidget *log_text_view;
static GtkTextBuffer *log_buffer;
static GPid ffmpeg_pid = 0;
static GIOChannel *ffmpeg_stdout_chan = NULL;
static GIOChannel *ffmpeg_stderr_chan = NULL;
static guint ffmpeg_stdout_watch = 0;
static guint ffmpeg_stderr_watch = 0;

static void update_output_label(void);

static GPtrArray *audio_codecs = NULL;
static GPtrArray *video_codecs = NULL;
static GPtrArray *container_formats = NULL;
static char *current_format = NULL;
static gboolean input_has_audio = FALSE;
static gboolean input_has_video = FALSE;
/* default codec strings are allocated when needed (avoid freeing literals) */
static char *default_audio_codec = NULL;
static char *default_video_codec = NULL;

/* Batch processing state */
static GPtrArray *batch_files = NULL; /* array of gchar* paths */
static gboolean batch_running = FALSE;
static guint batch_index = 0;
/* Batch dialog widgets (created on demand) */
static GtkWidget *batch_dialog = NULL;
static GtkWidget *batch_listbox = NULL;
static GtkWidget *batch_start_button = NULL;
static GtkWidget *batch_add_folder_button = NULL;
static GtkWidget *batch_add_files_button = NULL;
static GtkWidget *batch_remove_button = NULL;
static GtkWidget *batch_stop_button = NULL;

/* Forward declarations for batch functions */
static void open_batch_dialog(GtkWindow *parent);
static void batch_add_folder_clicked(GtkButton *button, gpointer user_data);
static void batch_add_files_clicked(GtkButton *button, gpointer user_data);
static void batch_remove_selected_clicked(GtkButton *button, gpointer user_data);
static void batch_start_clicked_cb(GtkButton *button, gpointer user_data);
static void batch_stop_clicked_cb(GtkButton *button, gpointer user_data);
static void process_next_in_batch(void);
static gboolean continue_batch_idle(gpointer user_data);
static void batch_row_selected_cb(GtkListBox *box, GtkListBoxRow *row, gpointer user_data);
static void batch_add_folder_native_response(GtkNativeDialog *native, gint response, gpointer user_data);
static void batch_add_files_native_response(GtkNativeDialog *native, gint response, gpointer user_data);
static void add_single_file_to_batch(GFile *file);
static gboolean batch_dialog_close_request_cb(GtkWindow *window, gpointer user_data);
static gboolean batch_has_path(const char *path);

static gboolean is_batch_dialog_open(void)
{
    return batch_dialog != NULL;
}

static gboolean can_enable_start_button(void)
{
    if (!input_file)
        return FALSE;
    if (ffmpeg_pid > 0)
        return FALSE;
    if (is_batch_dialog_open())
        return FALSE;
    return TRUE;
}

static void update_start_button_state(void)
{
    if (!start_button)
        return;
    gtk_widget_set_sensitive(start_button, can_enable_start_button());
}

/* Helper: add codec to array if not already present */
static void add_codec_if_missing(GPtrArray *arr, const char *codec)
{
    if (!arr || !codec) return;
    for (guint i = 0; i < arr->len; i++) {
        if (g_strcmp0(g_ptr_array_index(arr, i), codec) == 0)
            return;
    }
    g_ptr_array_add(arr, g_strdup(codec));
}

/* Reorder codecs in-place so that entries from `priority` appear first (in order).
 * 'priority' is a NULL-terminated array of strings. This moves matching items
 * to the front while preserving the relative order of remaining items.
 */
static void reorder_codecs_by_popularity(GPtrArray *arr, const char **priority)
{
    if (!arr || !priority) return;
    guint pos = 0;
    for (int p = 0; priority[p] != NULL; p++) {
        for (guint i = pos; i < arr->len; i++) {
            const char *name = g_ptr_array_index(arr, i);
            if (g_strcmp0(name, priority[p]) == 0) {
                gpointer elt = g_ptr_array_remove_index(arr, i);
                /* insert moves element to desired front position */
                g_ptr_array_insert(arr, pos, elt);
                pos++;
                break;
            }
        }
    }
}

/* Parse output of `ffmpeg -encoders` and populate audio_codecs/video_codecs. */
static void gather_ffmpeg_encoders(const char *ffmpeg_exe)
{
    gchar *cmd;
    gchar *stdout_str = NULL;
    gchar *stderr_str = NULL;
    gint exit_status = 0;

    if (!audio_codecs)
        audio_codecs = g_ptr_array_new_with_free_func(g_free);
    if (!video_codecs)
        video_codecs = g_ptr_array_new_with_free_func(g_free);

    add_codec_if_missing(audio_codecs, "copy");
    add_codec_if_missing(video_codecs, "copy");

    if (!ffmpeg_exe) {
        add_codec_if_missing(audio_codecs, "aac");
        add_codec_if_missing(audio_codecs, "mp3");
        /* Add libvorbis to the fallback list so 'ogg' / 'webm' defaults work
         * even when ffmpeg is not present on PATH. */
        add_codec_if_missing(audio_codecs, "libvorbis");
        add_codec_if_missing(audio_codecs, "opus");
        add_codec_if_missing(audio_codecs, "flac");
        add_codec_if_missing(video_codecs, "libx264");
        add_codec_if_missing(video_codecs, "libx265");
        add_codec_if_missing(video_codecs, "libvpx-vp9");
        add_codec_if_missing(video_codecs, "libaom-av1");
        /* Reorder popular codecs to the top */
        const char *audio_priority[] = {"copy", "aac", "mp3", "opus", "libvorbis", "flac", NULL};
        const char *video_priority[] = {"copy", "libx264", "libx265", "libvpx-vp9", "libaom-av1", NULL};
        reorder_codecs_by_popularity(audio_codecs, audio_priority);
        reorder_codecs_by_popularity(video_codecs, video_priority);
        return;
    }

    cmd = g_strdup_printf("%s -hide_banner -encoders", ffmpeg_exe);
    GError *error = NULL;
    if (!g_spawn_command_line_sync(cmd, &stdout_str, &stderr_str, &exit_status, &error)) {
        g_warning("Failed to run ffmpeg to list encoders: %s", error ? error->message : "");
        if (error) g_error_free(error);
        g_free(cmd);
        g_free(stdout_str);
        g_free(stderr_str);
        return;
    }
    g_free(cmd);

    if (exit_status != 0 || !stdout_str) {
        g_warning("ffmpeg -encoders failed: %s", stderr_str ? stderr_str : "unknown");
        g_free(stdout_str);
        g_free(stderr_str);
        return;
    }

    gchar **lines = g_strsplit(stdout_str, "\n", -1);
    for (gint i = 0; lines[i] != NULL; i++) {
        gchar *line = g_strstrip(lines[i]);
        if (line[0] == '\0') continue;
        if (g_str_has_prefix(line, "Encoders:") || g_strrstr(line, "-----") || g_str_has_prefix(line, " --"))
            continue;

        gchar **tokens = g_strsplit_set(line, " \t", -1);
        gint t = 0;
        while (tokens[t] && tokens[t][0] == '\0') t++;
        if (!tokens[t]) { g_strfreev(tokens); continue; }
        gchar *flags = tokens[t];
        t++;
        while (tokens[t] && tokens[t][0] != '\0' && !g_ascii_isalnum((guchar)tokens[t][0])) t++;
        if (!tokens[t]) { g_strfreev(tokens); continue; }
        gchar *enc = tokens[t];

        if (flags[0] == 'A') {
            add_codec_if_missing(audio_codecs, enc);
        } else if (flags[0] == 'V') {
            add_codec_if_missing(video_codecs, enc);
        }
        g_strfreev(tokens);
    }
    g_strfreev(lines);
    g_free(stdout_str);
    g_free(stderr_str);
}

/* Mapping from ffprobe codec names to common ffmpeg encoder names for best-match */
typedef struct {
    const char *codec;
    const char *encoder;
} CodecMap;

static const CodecMap video_encoder_map[] = {
    {"h264", "libx264"},
    {"hevc", "libx265"},
    {"h265", "libx265"},
    {"vp9", "libvpx-vp9"},
    {"av1", "libaom-av1"},
    {"mpeg4", "mpeg4"},
    {"theora", "libtheora"},
    {NULL, NULL}
};

static const CodecMap audio_encoder_map[] = {
    {"aac", "aac"},
    {"mp3", "libmp3lame"},
    {"opus", "libopus"},
    {"vorbis", "libvorbis"},
    {"flac", "flac"},
    {"ac3", "ac3"},
    {NULL, NULL}
};

/* Mapping from container/format name to preferred audio/video encoders */
typedef struct {
    const char *format;
    const char *audio;
    const char *video;
} FormatDefault;

static const FormatDefault format_defaults[] = {
    {"auto", NULL, NULL},
    {"avi", "mp3", "mpeg4"},
    {"mp4", "aac", "libx264"},
    {"mkv", "aac", "libx264"},
    {"webm", "libvorbis", "libvpx-vp9"},
    {"mov", "aac", "libx264"},
    {"mpeg", "mp2", "mpeg2video"},
    {"ogg", "libvorbis", NULL},
    {"mp3", "mp3", NULL},
    {"flac", "flac", NULL},
    {"wav", "pcm_s16le", NULL},
    {NULL, NULL, NULL}
};

/* forward declare function used below */
static gint find_best_encoder_in_array(GPtrArray *arr, const char *codec, const CodecMap *map);

static int find_format_index(const char *fmt)
{
    if (!container_formats || !fmt) return 0;
    for (guint i = 0; i < container_formats->len; i++) {
        const char *s = g_ptr_array_index(container_formats, i);
        if (g_strcmp0(s, fmt) == 0) return (int)i;
    }
    return 0;
}

/* Map common ffprobe 'format_name' tokens to our canonical container names */
static const char *map_probe_format_to_container(const char *probe)
{
    if (!probe) return NULL;
    if (g_strstr_len(probe, -1, "matroska") || g_strstr_len(probe, -1, "webm")) return "mkv";
    if (g_strstr_len(probe, -1, "mov") || g_strstr_len(probe, -1, "mp4") || g_strstr_len(probe, -1, "isom")) return "mp4";
    if (g_strstr_len(probe, -1, "avi")) return "avi";
    if (g_strstr_len(probe, -1, "mpeg") || g_strstr_len(probe, -1, "mpg") || g_strstr_len(probe, -1, "mpegts")) return "mpeg";
    if (g_strstr_len(probe, -1, "wav")) return "wav";
    if (g_strstr_len(probe, -1, "mp3")) return "mp3";
    if (g_strstr_len(probe, -1, "flac")) return "flac";
    if (g_strstr_len(probe, -1, "ogg")) return "ogg";
    if (g_strstr_len(probe, -1, "webm")) return "webm";
    return NULL;
}

/* Set audio/video codec combos to defaults for given format name (if available) */
static void set_codecs_for_format(const char *fmt)
{
    if (!fmt) return;
    /* If the user explicitly selected 'auto', behave like the Reset buttons
     * for both audio and video: apply detected/default selections so the UI
     * reflects what was detected from the input file. This makes selecting
     * Auto equivalent to resetting codecs to detected defaults. */
    if (g_strcmp0(fmt, "auto") == 0) {
        /* Audio reset logic */
        if (audio_codecs) {
            if (!input_has_audio) {
                gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_audio_check), FALSE);
                gtk_drop_down_set_selected(GTK_DROP_DOWN(audio_combo), 0);
                gtk_widget_set_sensitive(audio_combo, TRUE);
                gtk_widget_set_sensitive(reset_audio, !gtk_check_button_get_active(GTK_CHECK_BUTTON(copy_audio_check)));
            } else if (!default_audio_codec || g_strcmp0(default_audio_codec, "copy") == 0) {
                gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_audio_check), TRUE);
                gtk_widget_set_sensitive(audio_combo, FALSE);
                /* 'copy' is at index 1 (leading 'No audio' at 0) */
                gtk_drop_down_set_selected(GTK_DROP_DOWN(audio_combo), 1);
                gtk_widget_set_sensitive(reset_audio, FALSE);
            } else {
                gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_audio_check), FALSE);
                gtk_widget_set_sensitive(audio_combo, TRUE);
                int aidx = find_best_encoder_in_array(audio_codecs, default_audio_codec, audio_encoder_map);
                gtk_drop_down_set_selected(GTK_DROP_DOWN(audio_combo), aidx + 1);
                gtk_widget_set_sensitive(reset_audio, TRUE);
            }
        }

        /* Video reset logic */
        if (video_codecs) {
            if (!input_has_video) {
                gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_video_check), FALSE);
                gtk_drop_down_set_selected(GTK_DROP_DOWN(video_combo), 0);
                gtk_widget_set_sensitive(video_combo, TRUE);
                gtk_widget_set_sensitive(reset_video, !gtk_check_button_get_active(GTK_CHECK_BUTTON(copy_video_check)));
            } else if (!default_video_codec || g_strcmp0(default_video_codec, "copy") == 0) {
                gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_video_check), TRUE);
                gtk_widget_set_sensitive(video_combo, FALSE);
                /* 'copy' is at index 1 (leading 'No video' at 0) */
                gtk_drop_down_set_selected(GTK_DROP_DOWN(video_combo), 1);
                gtk_widget_set_sensitive(reset_video, FALSE);
            } else {
                gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_video_check), FALSE);
                gtk_widget_set_sensitive(video_combo, TRUE);
                int vidx = find_best_encoder_in_array(video_codecs, default_video_codec, video_encoder_map);
                gtk_drop_down_set_selected(GTK_DROP_DOWN(video_combo), vidx + 1);
                gtk_widget_set_sensitive(reset_video, TRUE);
            }
        }
        return;
    }
    const char *want_audio = NULL;
    const char *want_video = NULL;
    for (int i = 0; format_defaults[i].format != NULL; i++) {
        if (g_strcmp0(format_defaults[i].format, fmt) == 0) {
            want_audio = format_defaults[i].audio;
            want_video = format_defaults[i].video;
            break;
        }
    }

    if (want_audio && audio_codecs) {
        int idx = find_best_encoder_in_array(audio_codecs, want_audio, audio_encoder_map);
        gtk_drop_down_set_selected(GTK_DROP_DOWN(audio_combo), idx + 1);
    }
    if (want_video && video_codecs) {
        int idx = find_best_encoder_in_array(video_codecs, want_video, video_encoder_map);
        gtk_drop_down_set_selected(GTK_DROP_DOWN(video_combo), idx + 1);
        if (!gtk_check_button_get_active(GTK_CHECK_BUTTON(copy_video_check)))
            gtk_widget_set_sensitive(video_combo, TRUE);
        gtk_widget_set_sensitive(reset_video, !gtk_check_button_get_active(GTK_CHECK_BUTTON(copy_video_check)));
    } else {
        gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_video_check), FALSE);
        gtk_drop_down_set_selected(GTK_DROP_DOWN(video_combo), 0);
        gtk_widget_set_sensitive(video_combo, TRUE);
        gtk_widget_set_sensitive(reset_video, TRUE);
    }
}

/* Map simple format name to preferred extension (including dot). Return NULL to keep original. */
static const char *format_to_extension(const char *fmt)
{
    if (!fmt) return NULL;
    if (g_strcmp0(fmt, "auto") == 0) return NULL;
    if (g_strcmp0(fmt, "mp4") == 0) return ".mp4";
    if (g_strcmp0(fmt, "mkv") == 0) return ".mkv";
    if (g_strcmp0(fmt, "webm") == 0) return ".webm";
    if (g_strcmp0(fmt, "avi") == 0) return ".avi";
    if (g_strcmp0(fmt, "mov") == 0) return ".mov";
    if (g_strcmp0(fmt, "mpeg") == 0) return ".mpg";
    if (g_strcmp0(fmt, "mp3") == 0) return ".mp3";
    if (g_strcmp0(fmt, "flac") == 0) return ".flac";
    if (g_strcmp0(fmt, "wav") == 0) return ".wav";
    if (g_strcmp0(fmt, "ogg") == 0) return ".ogg";
    return NULL;
}

/* Helper: get active text from a GtkDropDown using the stored model */
static gchar *drop_down_get_active_text(GtkWidget *dropdown, GtkStringList *model)
{
    if (!dropdown || !model) return NULL;
    gint sel = gtk_drop_down_get_selected(GTK_DROP_DOWN(dropdown));
    if (sel < 0) return NULL;
    const char *s = gtk_string_list_get_string(model, sel);
    return s ? g_strdup(s) : NULL;
}

static void drop_down_set_items_from_ptrarray(GtkWidget *dropdown, GtkStringList **model_store, GPtrArray *arr, const char *leading)
{
    if (!dropdown) return;
    /* free old model if present */
    if (*model_store) {
        g_object_unref(*model_store);
        *model_store = NULL;
    }
    GtkStringList *m = gtk_string_list_new(NULL);
    if (leading)
        gtk_string_list_append(m, leading);
    if (arr) {
        for (guint i = 0; i < arr->len; i++) {
            const char *c = g_ptr_array_index(arr, i);
            gtk_string_list_append(m, c);
        }
    }
    /* set model on dropdown (takes a reference) */
    gtk_drop_down_set_model(GTK_DROP_DOWN(dropdown), (GListModel*)m);
    *model_store = m; /* keep reference so we can read values */
    /* default select first item */
    gtk_drop_down_set_selected(GTK_DROP_DOWN(dropdown), 0);
}

static void on_format_combo_changed_generic(GtkDropDown *combo, gpointer user_data)
{
    gchar *sel = drop_down_get_active_text(GTK_WIDGET(combo), format_model);
    if (!sel) return;
    /* If the user selects 'auto', leave copy checkboxes alone (auto-exempt).
     * For any other explicit format selection, clear both Copy checkboxes so
     * the user must explicitly choose codecs. */
    if (g_strcmp0(sel, "auto") != 0 && copy_audio_check && copy_video_check) {
        if (gtk_check_button_get_active(GTK_CHECK_BUTTON(copy_audio_check)))
            gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_audio_check), FALSE);
        if (gtk_check_button_get_active(GTK_CHECK_BUTTON(copy_video_check)))
            gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_video_check), FALSE);
        /* Ensure codec combos are enabled so user can pick encoders */
        gtk_widget_set_sensitive(audio_combo, TRUE);
        gtk_widget_set_sensitive(video_combo, TRUE);
        gtk_widget_set_sensitive(reset_audio, TRUE);
        gtk_widget_set_sensitive(reset_video, TRUE);
    }
    g_free(current_format);
    current_format = g_strdup(sel);
    set_codecs_for_format(sel);
    update_output_label();
    g_free(sel);
}


static gint find_best_encoder_in_array(GPtrArray *arr, const char *codec, const CodecMap *map)
{
    if (!arr || arr->len == 0) return 0;
    if (!codec) return 0;
    gchar *codec_l = g_utf8_strdown(codec, -1);
    for (guint i = 0; i < arr->len; i++) {
        const char *name = g_ptr_array_index(arr, i);
        if (g_strcmp0(name, codec) == 0) {
            g_free(codec_l);
            return i;
        }
    }
    if (map) {
        for (int m = 0; map[m].codec != NULL; m++) {
            if (g_strcmp0(map[m].codec, codec) == 0) {
                const char *want = map[m].encoder;
                for (guint i = 0; i < arr->len; i++) {
                    const char *name = g_ptr_array_index(arr, i);
                    if (g_strcmp0(name, want) == 0) {
                        g_free(codec_l);
                        return i;
                    }
                    gchar *name_l = g_utf8_strdown(name, -1);
                    if (g_strstr_len(name_l, -1, want)) {
                        g_free(name_l);
                        g_free(codec_l);
                        return i;
                    }
                    g_free(name_l);
                }
            }
        }
    }
    for (guint i = 0; i < arr->len; i++) {
        const char *name = g_ptr_array_index(arr, i);
        gchar *name_l = g_utf8_strdown(name, -1);
        if (g_strstr_len(name_l, -1, codec_l)) {
            g_free(name_l);
            g_free(codec_l);
            return i;
        }
        g_free(name_l);
    }
    g_free(codec_l);
    return 0;
}

/* Helper: show an alert dialog (non-blocking) */
static char *ffmpeg_path = NULL;
static char *ffprobe_path = NULL;

static void show_alert (GtkWindow *parent, const char *title, const char *body)
{
    AdwDialog *d = adw_alert_dialog_new (title, body);
    adw_alert_dialog_add_responses (ADW_ALERT_DIALOG (d), "ok", "_OK", NULL);
    adw_dialog_present (d, GTK_WIDGET (parent));
}

/* Forward declarations for IO/child callbacks */
static gboolean ffmpeg_stdout_cb(GIOChannel *source, GIOCondition condition, gpointer user_data);
static gboolean ffmpeg_stderr_cb(GIOChannel *source, GIOCondition condition, gpointer user_data);
static void ffmpeg_child_watch_cb(GPid pid, gint status, gpointer user_data);
static gboolean enable_ui_after_child(gpointer user_data);
static void on_stop_clicked(GtkButton *button, gpointer user_data);
/* (prototype already declared above) */

/* Detect default codecs from input file */
static void detect_defaults(const char *file) {
    gchar *ffprobe_path = g_find_program_in_path("ffprobe");
    if (!ffprobe_path) {
        g_warning("ffprobe not found in PATH; cannot detect codecs");
        return;
    }
    gchar *command = g_strdup_printf("%s -v quiet -print_format json -show_streams -show_format \"%s\"", ffprobe_path, file);
    gchar *stdout_str = NULL;
    gchar *stderr_str = NULL;
    gint exit_status;
    GError *error = NULL;

    if (!g_spawn_command_line_sync(command, &stdout_str, &stderr_str, &exit_status, &error)) {
        g_warning("Failed to run ffprobe: %s", error->message);
        g_error_free(error);
        g_free(command);
        return;
    }
    g_free(command);
    g_free(ffprobe_path);

    if (exit_status != 0) {
        g_warning("ffprobe failed: %s", stderr_str);
        g_free(stdout_str);
        g_free(stderr_str);
        return;
    }

    JsonParser *parser = json_parser_new();
    if (!json_parser_load_from_data(parser, stdout_str, -1, &error)) {
        g_warning("Failed to parse json: %s", error->message);
        g_error_free(error);
        g_object_unref(parser);
        g_free(stdout_str);
        g_free(stderr_str);
        return;
    }

    JsonNode *root = json_parser_get_root(parser);
    JsonObject *obj = json_node_get_object(root);
    JsonArray *streams = json_object_get_array_member(obj, "streams");

    JsonObject *format_obj = json_object_get_object_member(obj, "format");
    if (format_obj) {
        const char *fmt_name = json_object_get_string_member(format_obj, "format_name");
        if (fmt_name) {
            gchar **parts = g_strsplit(fmt_name, ",", 2);
            gchar *first = g_strstrip(parts[0]);
            gchar *low = g_utf8_strdown(first, -1);
            const char *mapped = map_probe_format_to_container(low);
            g_free(current_format);
            if (mapped)
                current_format = g_strdup(mapped);
            else
                current_format = g_strdup(low);
            g_free(low);
            g_strfreev(parts);
        }
    }

    input_has_audio = FALSE;
    input_has_video = FALSE;

    for (guint i = 0; i < json_array_get_length(streams); i++) {
        JsonNode *stream_node = json_array_get_element(streams, i);
        JsonObject *stream = json_node_get_object(stream_node);
        const char *codec_type = json_object_get_string_member(stream, "codec_type");
        const char *codec_name = json_object_get_string_member(stream, "codec_name");

        if (g_strcmp0(codec_type, "audio") == 0) {
            input_has_audio = TRUE;
            if (!default_audio_codec)
                default_audio_codec = g_strdup(codec_name);
        } else if (g_strcmp0(codec_type, "video") == 0) {
            input_has_video = TRUE;
            if (!default_video_codec)
                default_video_codec = g_strdup(codec_name);
        }
    }

    g_object_unref(parser);
    g_free(stdout_str);
    g_free(stderr_str);
}

/* Helper to update output filename */
static void update_output_label() {
    if (!input_file) return;
    char *dir = g_path_get_dirname(input_file);
    char *basename = g_path_get_basename(input_file);
    char *dot = strrchr(basename, '.');
    if (dot) {
        size_t name_len = dot - basename;
        char *name = g_strndup(basename, name_len);
        const char *orig_ext = dot;
        const char *new_ext = format_to_extension(current_format);
        if (!new_ext) new_ext = orig_ext;
        output_file = g_build_filename(dir, g_strdup_printf("%s_out%s", name, new_ext), NULL);
        g_free(name);
    } else {
        const char *new_ext = format_to_extension(current_format);
        if (new_ext)
            output_file = g_build_filename(dir, g_strdup_printf("%s_out%s", basename, new_ext), NULL);
        else
            output_file = g_build_filename(dir, g_strdup_printf("%s_out", basename), NULL);
    }
    gtk_label_set_text(GTK_LABEL(output_label), output_file);
    g_free(dir);
    g_free(basename);
}

/* Use the modern GtkFileDialog API (GTK >= 4.8) and open it asynchronously.
 * The finish callback will handle the selected file and update UI state. */
static void on_file_dialog_open_finish(GObject *source_object, GAsyncResult *res, gpointer user_data)
{
    GtkFileDialog *dialog = GTK_FILE_DIALOG(source_object);
    GError *error = NULL;
    GFile *file = gtk_file_dialog_open_finish(dialog, res, &error);
    if (!file) {
        if (error) {
            g_warning("File dialog error: %s", error->message);
            g_error_free(error);
        }
        g_object_unref(dialog);
        return;
    }

    input_file = g_file_get_path(file);
    gtk_label_set_text(GTK_LABEL(input_label), input_file);
    g_free(default_audio_codec);
    g_free(default_video_codec);
    default_audio_codec = NULL;
    default_video_codec = NULL;
    detect_defaults(input_file);
    if (!default_audio_codec) default_audio_codec = g_strdup("copy");
    if (!default_video_codec) default_video_codec = g_strdup("copy");

    int active_idx = 0;
    drop_down_set_items_from_ptrarray(audio_combo, &audio_model, audio_codecs, "No audio");
    if (!input_has_audio) active_idx = 0;
    else if (default_audio_codec) {
        int best = find_best_encoder_in_array(audio_codecs, default_audio_codec, audio_encoder_map);
        active_idx = best + 1;
    }
    gtk_drop_down_set_selected(GTK_DROP_DOWN(audio_combo), active_idx);

    active_idx = 0;
    drop_down_set_items_from_ptrarray(video_combo, &video_model, video_codecs, "No video");
    if (!input_has_video) active_idx = 0;
    else if (default_video_codec) {
        int best = find_best_encoder_in_array(video_codecs, default_video_codec, video_encoder_map);
        active_idx = best + 1;
    }
    gtk_drop_down_set_selected(GTK_DROP_DOWN(video_combo), active_idx);

    if (current_format) {
        int fidx = find_format_index(current_format);
        gtk_drop_down_set_selected(GTK_DROP_DOWN(format_combo_audio), fidx);
        set_codecs_for_format(current_format);
    } else {
        gtk_drop_down_set_selected(GTK_DROP_DOWN(format_combo_audio), 0);
    }
    update_output_label();
    /* Enable UI controls now that an input was selected. */
    update_start_button_state();
    /* Enable copy checkboxes so user can toggle copy behavior */
    gtk_widget_set_sensitive(copy_audio_check, TRUE);
    gtk_widget_set_sensitive(copy_video_check, TRUE);
    /* Format dropdown should be enabled */
    gtk_widget_set_sensitive(format_combo_audio, TRUE);
    /* Enable or disable audio controls based on detection and copy checkbox */
    if (input_has_audio) {
        /* If default is 'copy', set the checkbox active and disable combo */
        if (default_audio_codec && g_strcmp0(default_audio_codec, "copy") == 0) {
            gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_audio_check), TRUE);
            gtk_widget_set_sensitive(audio_combo, FALSE);
            gtk_widget_set_sensitive(reset_audio, FALSE);
        } else {
            gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_audio_check), FALSE);
            gtk_widget_set_sensitive(audio_combo, TRUE);
            gtk_widget_set_sensitive(reset_audio, TRUE);
        }
    } else {
        /* No audio: leave Copy unchecked and allow selection of 'No audio' */
        gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_audio_check), FALSE);
        gtk_widget_set_sensitive(audio_combo, TRUE);
        gtk_widget_set_sensitive(reset_audio, TRUE);
    }
    /* Enable or disable video controls based on detection and copy checkbox */
    if (input_has_video) {
        if (default_video_codec && g_strcmp0(default_video_codec, "copy") == 0) {
            gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_video_check), TRUE);
            gtk_widget_set_sensitive(video_combo, FALSE);
            gtk_widget_set_sensitive(reset_video, FALSE);
        } else {
            gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_video_check), FALSE);
            gtk_widget_set_sensitive(video_combo, TRUE);
            gtk_widget_set_sensitive(reset_video, TRUE);
        }
    } else {
        gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_video_check), FALSE);
        gtk_widget_set_sensitive(video_combo, TRUE);
        gtk_widget_set_sensitive(reset_video, TRUE);
    }
    /* Ensure Start/Stop reflect running state */
    gtk_widget_set_sensitive(stop_button, FALSE);
    g_object_unref(file);
    g_object_unref(dialog);
}

static void on_choose_file_clicked(GtkButton *button, gpointer user_data) {
    GtkWindow *window = GTK_WINDOW(user_data);
    GtkFileDialog *dialog = gtk_file_dialog_new();
    gtk_file_dialog_set_title(dialog, "Choose input file");
    /* Open asynchronously; the finish callback will handle the chosen file */
    gtk_file_dialog_open(dialog, window, NULL, on_file_dialog_open_finish, NULL);
}

static void on_copy_audio_toggled(GtkCheckButton *check, gpointer user_data) {
    gboolean copy = gtk_check_button_get_active(check);
    /* If conversion is running, keep combos disabled regardless */
    if (ffmpeg_pid > 0) {
        gtk_widget_set_sensitive(audio_combo, FALSE);
    } else {
        gtk_widget_set_sensitive(audio_combo, !copy);
    }
    /* Reset button should be disabled when copy is active */
    gtk_widget_set_sensitive(reset_audio, !copy);
    update_output_label();
}

static void on_copy_video_toggled(GtkCheckButton *check, gpointer user_data) {
    gboolean copy = gtk_check_button_get_active(check);
    if (ffmpeg_pid > 0) {
        gtk_widget_set_sensitive(video_combo, FALSE);
    } else {
        gtk_widget_set_sensitive(video_combo, !copy);
    }
    /* Reset button should be disabled when copy is active */
    gtk_widget_set_sensitive(reset_video, !copy);
    update_output_label();
}

/* Combo changes */
static void on_audio_combo_changed(GtkComboBox *combo, gpointer user_data) {
    gchar *sel = drop_down_get_active_text(GTK_WIDGET(combo), audio_model);
    if (sel) {
        if (g_strcmp0(sel, "copy") == 0 || g_strcmp0(sel, "Copy") == 0) {
            gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_audio_check), TRUE);
        } else {
            gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_audio_check), FALSE);
        }
        g_free(sel);
    }
    update_output_label();
}

static void on_video_combo_changed(GtkComboBox *combo, gpointer user_data) {
    gchar *sel = drop_down_get_active_text(GTK_WIDGET(combo), video_model);
    if (sel) {
        if (g_strcmp0(sel, "copy") == 0 || g_strcmp0(sel, "Copy") == 0) {
            gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_video_check), TRUE);
        } else {
            gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_video_check), FALSE);
        }
        g_free(sel);
    }
    update_output_label();
}

/* Reset buttons */
static void on_reset_audio_clicked(GtkButton *button, gpointer user_data) {
    if (!audio_codecs) return;
    /* If the input has no audio, reset to 'No audio' (index 0). */
    if (!input_has_audio) {
        /* No audio stream: ensure Copy is off and combobox shows 'No audio' */
        gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_audio_check), FALSE);
        gtk_drop_down_set_selected(GTK_DROP_DOWN(audio_combo), 0);
        gtk_widget_set_sensitive(audio_combo, TRUE);
        gtk_widget_set_sensitive(reset_audio, !gtk_check_button_get_active(GTK_CHECK_BUTTON(copy_audio_check)));
        return;
    }
    /* default_audio_codec should normally be set after file selection; if missing, default to 'copy' */
    if (!default_audio_codec || g_strcmp0(default_audio_codec, "copy") == 0) {
        /* Default is 'copy' -> enable the Copy checkbox and disable codec combobox */
        gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_audio_check), TRUE);
        gtk_widget_set_sensitive(audio_combo, FALSE);
        /* combobox layout: [No audio, copy, ...] -> 'copy' is index 1 */
    gtk_drop_down_set_selected(GTK_DROP_DOWN(audio_combo), 1);
        /* When Copy is active, reset button should be disabled */
        gtk_widget_set_sensitive(reset_audio, FALSE);
        return;
    }
    /* Non-copy default: ensure Copy is off and combo enabled */
    gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_audio_check), FALSE);
    gtk_widget_set_sensitive(audio_combo, TRUE);
    int idx = find_best_encoder_in_array(audio_codecs, default_audio_codec, audio_encoder_map);
    /* offset by 1 because combobox has a leading 'No audio' entry */
    gtk_drop_down_set_selected(GTK_DROP_DOWN(audio_combo), idx + 1);
    gtk_widget_set_sensitive(reset_audio, TRUE);
}

static void on_reset_video_clicked(GtkButton *button, gpointer user_data) {
    if (!video_codecs) return;
    /* If the input has no video, reset to 'No video' (index 0). */
    if (!input_has_video) {
        /* No video stream: ensure Copy is off and combobox shows 'No video' */
        gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_video_check), FALSE);
    gtk_drop_down_set_selected(GTK_DROP_DOWN(video_combo), 0);
        gtk_widget_set_sensitive(video_combo, TRUE);
        gtk_widget_set_sensitive(reset_video, !gtk_check_button_get_active(GTK_CHECK_BUTTON(copy_video_check)));
        return;
    }
    if (!default_video_codec || g_strcmp0(default_video_codec, "copy") == 0) {
        /* Default is 'copy' -> enable the Copy checkbox and disable codec combobox */
        gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_video_check), TRUE);
        gtk_widget_set_sensitive(video_combo, FALSE);
    gtk_drop_down_set_selected(GTK_DROP_DOWN(video_combo), 1);
        gtk_widget_set_sensitive(reset_video, FALSE);
        return;
    }
    /* Non-copy default: ensure Copy is off and combo enabled */
    gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_video_check), FALSE);
    gtk_widget_set_sensitive(video_combo, TRUE);
    int idx = find_best_encoder_in_array(video_codecs, default_video_codec, video_encoder_map);
    gtk_drop_down_set_selected(GTK_DROP_DOWN(video_combo), idx + 1);
    gtk_widget_set_sensitive(reset_video, TRUE);
}

/* Start conversion */
static void on_start_clicked(GtkButton *button, gpointer user_data) {
    // Disable all except stop
    gtk_widget_set_sensitive(start_button, FALSE);
    gtk_widget_set_sensitive(stop_button, TRUE);
    // Construct ffmpeg command
    /* Determine selections; combo boxes now have a 'No audio'/'No video' at index 0 */

    /* Build a human-readable preview command for log */
    gchar *command = g_strdup_printf("ffmpeg -i \"%s\" ... \"%s\"", input_file, output_file);
    gtk_text_buffer_set_text(log_buffer, "Starting conversion...\n", -1);
    gtk_text_buffer_insert_at_cursor(log_buffer, command, -1);
    gtk_text_buffer_insert_at_cursor(log_buffer, "\n", -1);

    /* Spawn ffmpeg using bare program name so PATH is used. If that fails with ENOENT,
     * retry with the resolved ffmpeg_path (if available). */
    gchar *audio_dup = NULL;
    gchar *video_dup = NULL;
    if (gtk_check_button_get_active(GTK_CHECK_BUTTON(copy_audio_check)))
        audio_dup = g_strdup("copy");
    else
        audio_dup = drop_down_get_active_text(audio_combo, audio_model);
    if (gtk_check_button_get_active(GTK_CHECK_BUTTON(copy_video_check)))
        video_dup = g_strdup("copy");
    else
        video_dup = drop_down_get_active_text(video_combo, video_model);

    gchar *argv_spawn[12];
    int argc_spawn = 0;
    argv_spawn[argc_spawn++] = "ffmpeg";
    argv_spawn[argc_spawn++] = "-y"; /* overwrite output */
    argv_spawn[argc_spawn++] = "-i";
    argv_spawn[argc_spawn++] = (gchar *)input_file;
    /* Handle "No audio" / "No video" selections: pass -an / -vn instead of codec flags */
    if (audio_dup && g_strcmp0(audio_dup, "No audio") == 0) {
        argv_spawn[argc_spawn++] = "-an";
    } else {
        argv_spawn[argc_spawn++] = "-c:a";
        argv_spawn[argc_spawn++] = audio_dup;
    }
    if (video_dup && g_strcmp0(video_dup, "No video") == 0) {
        argv_spawn[argc_spawn++] = "-vn";
    } else {
        argv_spawn[argc_spawn++] = "-c:v";
        argv_spawn[argc_spawn++] = video_dup;
    }
    argv_spawn[argc_spawn++] = (gchar *)output_file;
    argv_spawn[argc_spawn] = NULL;

    /* Log which executable will be used (argv[0]) */
    gchar *which = g_strdup(argv_spawn[0]);
    gchar *which_msg = g_strdup_printf("Spawning: %s\n", which);
    gtk_text_buffer_insert_at_cursor(log_buffer, which_msg, -1);
    g_free(which_msg);
    g_free(which);

    GError *error = NULL;
    gint stdin_fd = -1, stdout_fd = -1, stderr_fd = -1;
    gboolean spawned = g_spawn_async_with_pipes(NULL, argv_spawn, NULL, G_SPAWN_DO_NOT_REAP_CHILD | G_SPAWN_SEARCH_PATH, NULL, NULL, &ffmpeg_pid, &stdin_fd, &stdout_fd, &stderr_fd, &error);
    if (!spawned) {
        /* If the error indicates executable not found, try resolved ffmpeg_path */
        if (error && error->domain == G_SPAWN_ERROR && error->code == G_SPAWN_ERROR_NOENT && ffmpeg_path) {
            g_clear_error(&error);
            argv_spawn[0] = ffmpeg_path; /* use full path */
            spawned = g_spawn_async_with_pipes(NULL, argv_spawn, NULL, G_SPAWN_DO_NOT_REAP_CHILD, NULL, NULL, &ffmpeg_pid, &stdin_fd, &stdout_fd, &stderr_fd, &error);
        }
    }

    if (!spawned) {
        const char *msg = error ? error->message : "Failed to spawn ffmpeg";
        gtk_text_buffer_insert_at_cursor(log_buffer, msg, -1);
        gtk_text_buffer_insert_at_cursor(log_buffer, "\n", -1);
    /* show alert to user (no parent available here) */
    show_alert(NULL, "ffmpeg error", msg);
    /* Restore UI since spawn failed */
    update_start_button_state();
    gtk_widget_set_sensitive(stop_button, FALSE);
        if (error) g_error_free(error);
        g_free(audio_dup);
        g_free(video_dup);
        g_free(command);
        return;
    }

    /* Set up GIO channels to read ffmpeg stdout/stderr and watch the child process */
    if (stdin_fd != -1) close(stdin_fd); /* we don't write to ffmpeg stdin */
    if (stdout_fd != -1) {
        ffmpeg_stdout_chan = g_io_channel_unix_new(stdout_fd);
        g_io_channel_set_encoding(ffmpeg_stdout_chan, NULL, NULL);
        g_io_channel_set_buffered(ffmpeg_stdout_chan, FALSE);
        ffmpeg_stdout_watch = g_io_add_watch(ffmpeg_stdout_chan, G_IO_IN | G_IO_HUP | G_IO_ERR, ffmpeg_stdout_cb, NULL);
    }
    if (stderr_fd != -1) {
        ffmpeg_stderr_chan = g_io_channel_unix_new(stderr_fd);
        g_io_channel_set_encoding(ffmpeg_stderr_chan, NULL, NULL);
        g_io_channel_set_buffered(ffmpeg_stderr_chan, FALSE);
        ffmpeg_stderr_watch = g_io_add_watch(ffmpeg_stderr_chan, G_IO_IN | G_IO_HUP | G_IO_ERR, ffmpeg_stderr_cb, NULL);
    }
    /* Watch the child so we can cleanup when it exits */
    g_child_watch_add(ffmpeg_pid, ffmpeg_child_watch_cb, NULL);
    g_free(audio_dup);
    g_free(video_dup);
    g_free(command);
    /* Disable codec selection while conversion is running */
    gtk_widget_set_sensitive(audio_combo, FALSE);
    gtk_widget_set_sensitive(video_combo, FALSE);
    // TODO: watch for output, but for now, just start
}

/* Child and IO callbacks */
static gboolean enable_ui_after_child(gpointer user_data) {
    update_start_button_state();
    gtk_widget_set_sensitive(stop_button, FALSE);
    /* Re-enable codec combos unless their 'Copy' checkboxes are active */
    if (!gtk_check_button_get_active(GTK_CHECK_BUTTON(copy_audio_check)))
        gtk_widget_set_sensitive(audio_combo, TRUE);
    else
        gtk_widget_set_sensitive(audio_combo, FALSE);
    if (!gtk_check_button_get_active(GTK_CHECK_BUTTON(copy_video_check)))
        gtk_widget_set_sensitive(video_combo, TRUE);
    else
        gtk_widget_set_sensitive(video_combo, FALSE);
    return G_SOURCE_REMOVE;
}

static void ffmpeg_child_watch_cb(GPid pid, gint status, gpointer user_data) {
    GtkTextIter end;
    gtk_text_buffer_get_end_iter(log_buffer, &end);
    if (WIFEXITED(status)) {
        int code = WEXITSTATUS(status);
        gchar *msg = g_strdup_printf("ffmpeg (pid %d) exited normally with code %d\n", pid, code);
        gtk_text_buffer_insert(log_buffer, &end, msg, -1);
        g_free(msg);
    } else if (WIFSIGNALED(status)) {
        int sig = WTERMSIG(status);
        gchar *msg = g_strdup_printf("ffmpeg (pid %d) terminated by signal %d (%s)\n", pid, sig, strsignal(sig));
        gtk_text_buffer_insert(log_buffer, &end, msg, -1);
        g_free(msg);
    } else {
        gchar *msg = g_strdup_printf("ffmpeg (pid %d) exited with status %d\n", pid, status);
        gtk_text_buffer_insert(log_buffer, &end, msg, -1);
        g_free(msg);
    }
    g_spawn_close_pid(pid);
    g_idle_add(enable_ui_after_child, NULL);
    if (ffmpeg_pid == pid) ffmpeg_pid = 0;
    /* If batch mode is running, schedule continuation to next file */
    if (batch_running) {
        /* schedule on main loop to avoid reentrancy in child watch */
        g_idle_add(continue_batch_idle, NULL);
    }
}

/* Continue batch processing on idle (called after a conversion finishes) */
static gboolean continue_batch_idle(gpointer user_data)
{
    process_next_in_batch();
    return G_SOURCE_REMOVE;
}

/* Collect files recursively from a folder GFile and append to batch_files and listbox */
static void collect_files_from_folder(GFile *folder)
{
    if (!folder) return;
    GError *err = NULL;
    /* Request content-type so we can filter non-media files */
    const char *attrs = G_FILE_ATTRIBUTE_STANDARD_NAME "," G_FILE_ATTRIBUTE_STANDARD_TYPE ",standard::content-type";
    GFileEnumerator *enumerator = g_file_enumerate_children(folder, attrs, G_FILE_QUERY_INFO_NONE, NULL, &err);
    if (!enumerator) {
        if (err) g_error_free(err);
        return;
    }
    GFileInfo *info;
    while ((info = g_file_enumerator_next_file(enumerator, NULL, &err)) != NULL) {
        const char *name = g_file_info_get_name(info);
        GFile *child = g_file_get_child(folder, name);
        GFileType type = g_file_info_get_file_type(info);
        if (type == G_FILE_TYPE_DIRECTORY) {
            collect_files_from_folder(child);
        } else if (type == G_FILE_TYPE_REGULAR) {
            /* check content-type first; if missing, fall back to extension matching */
            const char *ctype = g_file_info_get_content_type(info);
            gboolean is_media = FALSE;
            if (ctype) {
                if (g_str_has_prefix(ctype, "audio/") || g_str_has_prefix(ctype, "video/"))
                    is_media = TRUE;
            }
            if (!is_media) {
                /* fallback: check extension */
                char *path = g_file_get_path(child);
                if (path) {
                    const char *ext = strrchr(path, '.');
                    if (ext) {
                        gchar *ext_l = g_utf8_strdown(ext + 1, -1);
                        const char *good_exts[] = {"mp4","mkv","webm","avi","mov","mpeg","mpg","mp3","flac","wav","ogg","aac","m4a","opus","m4v","webm","m2ts", NULL};
                        for (int i = 0; good_exts[i] != NULL; i++) {
                            if (g_strcmp0(ext_l, good_exts[i]) == 0) { is_media = TRUE; break; }
                        }
                        g_free(ext_l);
                    }
                    g_free(path);
                }
            }
            if (is_media) {
                char *path = g_file_get_path(child);
                if (path) {
                    if (!batch_has_path(path)) {
                        if (!batch_files) batch_files = g_ptr_array_new_with_free_func(g_free);
                        g_ptr_array_add(batch_files, g_strdup(path));
                        if (batch_listbox) {
                            GtkWidget *row = gtk_label_new(path);
                            /* left align and ellipsize start so filename at end stays visible */
                            gtk_label_set_xalign(GTK_LABEL(row), 0.0);
                            gtk_label_set_ellipsize(GTK_LABEL(row), PANGO_ELLIPSIZE_START);
                            /* show tooltip with full path */
                            gtk_widget_set_tooltip_text(row, path);
                            gtk_list_box_insert(GTK_LIST_BOX(batch_listbox), row, -1);
                                gtk_widget_set_visible(row, TRUE);
                                /* Select the first row in the list so the first item is applied */
                                {
                                    GtkListBoxRow *to_select = gtk_list_box_get_row_at_index(GTK_LIST_BOX(batch_listbox), 0);
                                    if (to_select) gtk_list_box_select_row(GTK_LIST_BOX(batch_listbox), to_select);
                                }
                        }
                    }
                    g_free(path);
                }
            }
        }
        g_object_unref(child);
        g_object_unref(info);
    }
    if (err) g_error_free(err);
    g_object_unref(enumerator);
}

static void batch_add_folder_clicked(GtkButton *button, gpointer user_data)
{
    GtkWindow *parent = GTK_WINDOW(user_data);
    /* Use native file chooser in folder-selection mode */
    GtkFileChooserNative *native = gtk_file_chooser_native_new("Select folder to add", parent, GTK_FILE_CHOOSER_ACTION_SELECT_FOLDER, "Add", "Cancel");
    /* Connect response handler */
    g_signal_connect(native, "response", G_CALLBACK(batch_add_folder_native_response), native);
    gtk_native_dialog_show(GTK_NATIVE_DIALOG(native));
}

static void batch_add_folder_native_response(GtkNativeDialog *native, gint response, gpointer user_data)
{
    GtkFileChooserNative *chooser = GTK_FILE_CHOOSER_NATIVE(native);
    if (response == GTK_RESPONSE_ACCEPT) {
        GFile *f = gtk_file_chooser_get_file(GTK_FILE_CHOOSER(chooser));
        if (f) {
            collect_files_from_folder(f);
            g_object_unref(f);
        }
    }
    /* destroy the dialog */
    gtk_native_dialog_destroy(native);
}

static void batch_remove_selected_clicked(GtkButton *button, gpointer user_data)
{
    if (!batch_listbox || !batch_files) return;
    GList *selected = gtk_list_box_get_selected_rows(GTK_LIST_BOX(batch_listbox));
    if (!selected) return;
    gint min_index = -1;
    /* find minimal index among selected rows via gtk_list_box_row_get_index */
    for (GList *l = selected; l; l = l->next) {
        GtkListBoxRow *sel_row = GTK_LIST_BOX_ROW(l->data);
        gint idx = gtk_list_box_row_get_index(sel_row);
        if (idx >= 0 && (min_index == -1 || idx < min_index)) min_index = idx;
    }
    /* Remove selected rows and corresponding paths */
    for (GList *l = selected; l; l = l->next) {
        GtkListBoxRow *sel_row = GTK_LIST_BOX_ROW(l->data);
        GtkWidget *child = gtk_list_box_row_get_child(sel_row);
        const char *text = NULL;
        if (child && GTK_IS_LABEL(child)) text = gtk_label_get_text(GTK_LABEL(child));
        if (text) {
            for (guint i = 0; i < batch_files->len; i++) {
                char *p = g_ptr_array_index(batch_files, i);
                if (g_strcmp0(p, text) == 0) {
                    g_ptr_array_remove_index(batch_files, i);
                    break;
                }
            }
        }
        gtk_list_box_remove(GTK_LIST_BOX(batch_listbox), GTK_WIDGET(sel_row));
    }
    /* After removals, select the next appropriate row: try to select the row at
     * min_index; if it doesn't exist (past end), try previous indices down to 0. */
    if (min_index >= 0) {
        for (gint sel_index = min_index; sel_index >= 0; sel_index--) {
            GtkListBoxRow *to_select = gtk_list_box_get_row_at_index(GTK_LIST_BOX(batch_listbox), sel_index);
            if (to_select) {
                gtk_list_box_select_row(GTK_LIST_BOX(batch_listbox), to_select);
                break;
            }
        }
    }
    g_list_free(selected);
}

static void batch_start_clicked_cb(GtkButton *button, gpointer user_data)
{
    if (!batch_files || batch_files->len == 0) return;
    batch_running = TRUE;
    batch_index = 0;
    /* disable add/remove while running */
    if (batch_add_folder_button) gtk_widget_set_sensitive(batch_add_folder_button, FALSE);
    if (batch_add_files_button) gtk_widget_set_sensitive(batch_add_files_button, FALSE);
    if (batch_remove_button) gtk_widget_set_sensitive(batch_remove_button, FALSE);
    if (batch_start_button) gtk_widget_set_sensitive(batch_start_button, FALSE);
    if (batch_stop_button) gtk_widget_set_sensitive(batch_stop_button, TRUE);
    /* disable listbox so user can't change selection during batch */
    if (batch_listbox) gtk_widget_set_sensitive(batch_listbox, FALSE);
    process_next_in_batch();
}

static void batch_stop_clicked_cb(GtkButton *button, gpointer user_data)
{
    batch_running = FALSE;
    /* Re-enable controls */
    if (batch_add_folder_button) gtk_widget_set_sensitive(batch_add_folder_button, TRUE);
    if (batch_add_files_button) gtk_widget_set_sensitive(batch_add_files_button, TRUE);
    if (batch_remove_button) gtk_widget_set_sensitive(batch_remove_button, TRUE);
    if (batch_start_button) gtk_widget_set_sensitive(batch_start_button, TRUE);
    if (batch_stop_button) gtk_widget_set_sensitive(batch_stop_button, FALSE);
    if (batch_listbox) gtk_widget_set_sensitive(batch_listbox, TRUE);
    /* Also stop any running ffmpeg process */
    on_stop_clicked(NULL, NULL);
}

/* Start processing next file in batch (if any). This will set input_file/output_file and
 * trigger the normal on_start_clicked logic. It will skip autodetection (so do not call
 * detect_defaults) as requested and reuse current UI settings. */
static void process_next_in_batch(void)
{
    if (!batch_running) return;
    if (!batch_files || batch_index >= batch_files->len) {
        /* finished */
        batch_running = FALSE;
        if (batch_add_folder_button) gtk_widget_set_sensitive(batch_add_folder_button, TRUE);
        if (batch_add_files_button) gtk_widget_set_sensitive(batch_add_files_button, TRUE);
        if (batch_remove_button) gtk_widget_set_sensitive(batch_remove_button, TRUE);
        if (batch_start_button) gtk_widget_set_sensitive(batch_start_button, TRUE);
        if (batch_stop_button) gtk_widget_set_sensitive(batch_stop_button, FALSE);
        if (batch_listbox) gtk_widget_set_sensitive(batch_listbox, TRUE);
        gtk_text_buffer_insert_at_cursor(log_buffer, "Batch finished.\n", -1);
        return;
    }
    /* Set input_file to next path, but DO NOT call detect_defaults (skip autodetection) */
    char *next = g_strdup(g_ptr_array_index(batch_files, batch_index));
    g_free(input_file);
    input_file = next;
    gtk_label_set_text(GTK_LABEL(input_label), input_file);
    /* Update output_file using current format selection */
    update_output_label();
    /* Start conversion using existing UI settings */
    /* Reuse on_start_clicked but it's tied to button; call directly */
    on_start_clicked(GTK_BUTTON(start_button), NULL);
    /* increment index for next time (we continue after child exits) */
    batch_index++;
}

/* Open batch dialog: simple window with list and controls */
static void open_batch_dialog(GtkWindow *parent)
{
    if (start_button)
        gtk_widget_set_sensitive(start_button, FALSE);
    if (batch_dialog) {
        gtk_window_present(GTK_WINDOW(batch_dialog));
        return;
    }
    batch_dialog = gtk_window_new();
    gtk_window_set_title(GTK_WINDOW(batch_dialog), "Batch processing");
    gtk_window_set_default_size(GTK_WINDOW(batch_dialog), 600, 400);
    /* When the dialog/window is closed by the user, clear the global widget
     * pointers so open_batch_dialog() can recreate the dialog later. */
    g_signal_connect(batch_dialog, "close-request", G_CALLBACK(batch_dialog_close_request_cb), NULL);
    GtkWidget *vbox = gtk_box_new(GTK_ORIENTATION_VERTICAL, 8);
    gtk_widget_set_margin_top(vbox, 8);
    gtk_widget_set_margin_bottom(vbox, 8);
    gtk_widget_set_margin_start(vbox, 8);
    gtk_widget_set_margin_end(vbox, 8);
    batch_listbox = gtk_list_box_new();
    g_signal_connect(batch_listbox, "row-selected", G_CALLBACK(batch_row_selected_cb), NULL);
    gtk_widget_set_vexpand(batch_listbox, TRUE);
    gtk_box_append(GTK_BOX(vbox), batch_listbox);
    GtkWidget *h = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    batch_add_folder_button = gtk_button_new_with_label("Add folder");
    g_signal_connect(batch_add_folder_button, "clicked", G_CALLBACK(batch_add_folder_clicked), batch_dialog);
    gtk_box_append(GTK_BOX(h), batch_add_folder_button);
    batch_add_files_button = gtk_button_new_with_label("Add file(s)");
    g_signal_connect(batch_add_files_button, "clicked", G_CALLBACK(batch_add_files_clicked), batch_dialog);
    gtk_box_append(GTK_BOX(h), batch_add_files_button);
    batch_remove_button = gtk_button_new_with_label("Remove selected");
    g_signal_connect(batch_remove_button, "clicked", G_CALLBACK(batch_remove_selected_clicked), NULL);
    gtk_box_append(GTK_BOX(h), batch_remove_button);
    batch_start_button = gtk_button_new_with_label("Start batch");
    g_signal_connect(batch_start_button, "clicked", G_CALLBACK(batch_start_clicked_cb), NULL);
    gtk_box_append(GTK_BOX(h), batch_start_button);
    batch_stop_button = gtk_button_new_with_label("Stop batch");
    g_signal_connect(batch_stop_button, "clicked", G_CALLBACK(batch_stop_clicked_cb), NULL);
    gtk_widget_set_sensitive(batch_stop_button, FALSE);
    gtk_box_append(GTK_BOX(h), batch_stop_button);
    gtk_box_append(GTK_BOX(vbox), h);
    gtk_window_set_child(GTK_WINDOW(batch_dialog), vbox);
    gtk_window_present(GTK_WINDOW(batch_dialog));
    if (!batch_files) batch_files = g_ptr_array_new_with_free_func(g_free);
    /* Populate existing batch entries into listbox */
    for (guint i = 0; i < batch_files->len; i++) {
        char *p = g_ptr_array_index(batch_files, i);
        GtkWidget *row = gtk_label_new(p);
        gtk_label_set_xalign(GTK_LABEL(row), 0.0);
        gtk_label_set_ellipsize(GTK_LABEL(row), PANGO_ELLIPSIZE_START);
        gtk_widget_set_tooltip_text(row, p);
        gtk_list_box_insert(GTK_LIST_BOX(batch_listbox), row, -1);
        gtk_widget_set_visible(row, TRUE);
    }
}

static gboolean batch_dialog_close_request_cb(GtkWindow *window, gpointer user_data)
{
    /* Clear widget globals so the dialog can be recreated later. Keep batch_files
     * intact (we want to preserve the queued paths). */
    batch_listbox = NULL;
    batch_add_folder_button = NULL;
    batch_add_files_button = NULL;
    batch_remove_button = NULL;
    batch_start_button = NULL;
    batch_stop_button = NULL;
    batch_dialog = NULL;
    update_start_button_state();
    /* Allow default handler to continue (destroy the window) */
    return FALSE;
}

static void add_single_file_to_batch(GFile *file)
{
    if (!file) return;
    char *path = g_file_get_path(file);
    if (!path) return;
    /* check for duplicates */
    if (batch_has_path(path)) { g_free(path); return; }
    /* check media type same as folder logic */
    GFileInfo *info = g_file_query_info(file, "standard::content-type", G_FILE_QUERY_INFO_NONE, NULL, NULL);
    gboolean is_media = FALSE;
    if (info) {
        const char *ctype = g_file_info_get_content_type(info);
        if (ctype && (g_str_has_prefix(ctype, "audio/") || g_str_has_prefix(ctype, "video/"))) is_media = TRUE;
        g_object_unref(info);
    }
    if (!is_media) {
        const char *ext = strrchr(path, '.');
        if (ext) {
            gchar *ext_l = g_utf8_strdown(ext + 1, -1);
            const char *good_exts[] = {"mp4","mkv","webm","avi","mov","mpeg","mpg","mp3","flac","wav","ogg","aac","m4a","opus","m4v","m2ts", NULL};
            for (int i = 0; good_exts[i] != NULL; i++) {
                if (g_strcmp0(ext_l, good_exts[i]) == 0) { is_media = TRUE; break; }
            }
            g_free(ext_l);
        }
    }
    if (!is_media) { g_free(path); return; }

    if (!batch_files) batch_files = g_ptr_array_new_with_free_func(g_free);
    g_ptr_array_add(batch_files, g_strdup(path));
    if (batch_listbox) {
        GtkWidget *row = gtk_label_new(path);
        gtk_label_set_xalign(GTK_LABEL(row), 0.0);
        gtk_label_set_ellipsize(GTK_LABEL(row), PANGO_ELLIPSIZE_START);
        gtk_widget_set_tooltip_text(row, path);
        gtk_list_box_insert(GTK_LIST_BOX(batch_listbox), row, -1);
        gtk_widget_set_visible(row, TRUE);
        /* Select the first row in the list so the first item is applied */
        {
            GtkListBoxRow *to_select = gtk_list_box_get_row_at_index(GTK_LIST_BOX(batch_listbox), 0);
            if (to_select) gtk_list_box_select_row(GTK_LIST_BOX(batch_listbox), to_select);
        }
    }
    g_free(path);
}

static void batch_add_files_clicked(GtkButton *button, gpointer user_data)
{
    GtkWindow *parent = GTK_WINDOW(user_data);
    GtkFileChooserNative *native = gtk_file_chooser_native_new("Select files to add", parent, GTK_FILE_CHOOSER_ACTION_OPEN, "Add", "Cancel");
    gtk_file_chooser_set_select_multiple(GTK_FILE_CHOOSER(native), TRUE);
    g_signal_connect(native, "response", G_CALLBACK(batch_add_files_native_response), native);
    gtk_native_dialog_show(GTK_NATIVE_DIALOG(native));
}

static void batch_add_files_native_response(GtkNativeDialog *native, gint response, gpointer user_data)
{
    GtkFileChooserNative *chooser = GTK_FILE_CHOOSER_NATIVE(native);
    if (response == GTK_RESPONSE_ACCEPT) {
        GListModel *files = gtk_file_chooser_get_files(GTK_FILE_CHOOSER(chooser));
        if (files) {
            gsize n = g_list_model_get_n_items(files);
            for (gsize i = 0; i < n; i++) {
                GFile *f = G_FILE(g_list_model_get_item(files, i));
                if (f) {
                    add_single_file_to_batch(f);
                    g_object_unref(f);
                }
            }
            g_object_unref(files);
        }
    }
    gtk_native_dialog_destroy(native);
}

/* Helper: check whether a given path is already present in batch_files */
static gboolean batch_has_path(const char *path)
{
    if (!path || !batch_files) return FALSE;
    for (guint i = 0; i < batch_files->len; i++) {
        char *p = g_ptr_array_index(batch_files, i);
        if (g_strcmp0(p, path) == 0) return TRUE;
    }
    return FALSE;
}

/* Helper: apply a file path as if chosen via file dialog (run autodetection and update UI) */
static void set_input_and_update_ui(const char *path)
{
    if (!path) return;
    g_free(input_file);
    input_file = g_strdup(path);
    gtk_label_set_text(GTK_LABEL(input_label), input_file);
    g_free(default_audio_codec);
    g_free(default_video_codec);
    default_audio_codec = NULL;
    default_video_codec = NULL;
    /* run autodetection */
    detect_defaults(input_file);
    if (!default_audio_codec) default_audio_codec = g_strdup("copy");
    if (!default_video_codec) default_video_codec = g_strdup("copy");

    int active_idx = 0;
    drop_down_set_items_from_ptrarray(audio_combo, &audio_model, audio_codecs, "No audio");
    if (!input_has_audio) active_idx = 0;
    else if (default_audio_codec) {
        int best = find_best_encoder_in_array(audio_codecs, default_audio_codec, audio_encoder_map);
        active_idx = best + 1;
    }
    gtk_drop_down_set_selected(GTK_DROP_DOWN(audio_combo), active_idx);

    active_idx = 0;
    drop_down_set_items_from_ptrarray(video_combo, &video_model, video_codecs, "No video");
    if (!input_has_video) active_idx = 0;
    else if (default_video_codec) {
        int best = find_best_encoder_in_array(video_codecs, default_video_codec, video_encoder_map);
        active_idx = best + 1;
    }
    gtk_drop_down_set_selected(GTK_DROP_DOWN(video_combo), active_idx);

    if (current_format) {
        int fidx = find_format_index(current_format);
        gtk_drop_down_set_selected(GTK_DROP_DOWN(format_combo_audio), fidx);
        set_codecs_for_format(current_format);
    } else {
        gtk_drop_down_set_selected(GTK_DROP_DOWN(format_combo_audio), 0);
    }
    update_output_label();
    /* Enable UI controls now that an input was selected. */
    update_start_button_state();
    gtk_widget_set_sensitive(copy_audio_check, TRUE);
    gtk_widget_set_sensitive(copy_video_check, TRUE);
    gtk_widget_set_sensitive(format_combo_audio, TRUE);
    if (input_has_audio) {
        if (default_audio_codec && g_strcmp0(default_audio_codec, "copy") == 0) {
            gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_audio_check), TRUE);
            gtk_widget_set_sensitive(audio_combo, FALSE);
            gtk_widget_set_sensitive(reset_audio, FALSE);
        } else {
            gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_audio_check), FALSE);
            gtk_widget_set_sensitive(audio_combo, TRUE);
            gtk_widget_set_sensitive(reset_audio, TRUE);
        }
    } else {
        gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_audio_check), FALSE);
        gtk_widget_set_sensitive(audio_combo, TRUE);
        gtk_widget_set_sensitive(reset_audio, TRUE);
    }
    if (input_has_video) {
        if (default_video_codec && g_strcmp0(default_video_codec, "copy") == 0) {
            gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_video_check), TRUE);
            gtk_widget_set_sensitive(video_combo, FALSE);
            gtk_widget_set_sensitive(reset_video, FALSE);
        } else {
            gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_video_check), FALSE);
            gtk_widget_set_sensitive(video_combo, TRUE);
            gtk_widget_set_sensitive(reset_video, TRUE);
        }
    } else {
        gtk_check_button_set_active(GTK_CHECK_BUTTON(copy_video_check), FALSE);
        gtk_widget_set_sensitive(video_combo, TRUE);
        gtk_widget_set_sensitive(reset_video, TRUE);
    }
    gtk_widget_set_sensitive(stop_button, FALSE);
}

/* Callback: when a row in the batch list is selected, apply that file to main UI */
static void batch_row_selected_cb(GtkListBox *box, GtkListBoxRow *row, gpointer user_data)
{
    if (!row) return;
    GtkWidget *child = gtk_list_box_row_get_child(row);
    if (!child) return;
    const char *text = NULL;
    if (GTK_IS_LABEL(child)) {
        text = gtk_label_get_text(GTK_LABEL(child));
    } else {
        /* If the child is a container, try to find a label by iterating its children using GTK's
         * widget iterator helpers: use gtk_widget_get_first_child and gtk_widget_get_next_sibling
         * are not part of stable public API; instead assume our rows are simple labels for now. */
        return;
    }
    if (text) set_input_and_update_ui(text);
}

/* Wrapper used for the Batch button 'clicked' signal: the signal provides the
 * GtkButton* as first arg and user_data is the parent window we passed. */
static void on_batch_button_clicked(GtkButton *button, gpointer user_data)
{
    GtkWindow *parent = GTK_WINDOW(user_data);
    open_batch_dialog(parent);
}

static gboolean ffmpeg_stdout_cb(GIOChannel *source, GIOCondition condition, gpointer user_data) {
    if (condition & (G_IO_HUP | G_IO_ERR)) {
        return FALSE;
    }
    GError *err = NULL;
    GString *buf = g_string_new(NULL);
    gchar tmp[1024];
    gsize bytes_read = 0;
    GIOStatus st = g_io_channel_read_chars(source, tmp, sizeof(tmp)-1, &bytes_read, &err);
    if (st == G_IO_STATUS_ERROR) {
        if (err) g_error_free(err);
        g_string_free(buf, TRUE);
        return FALSE;
    }
    if (bytes_read > 0) {
        tmp[bytes_read] = '\0';
        g_string_append(buf, tmp);
        /* Insert into text buffer and ensure view scrolls to the end */
        gtk_text_buffer_insert_at_cursor(log_buffer, buf->str, -1);
        GtkTextIter end;
        gtk_text_buffer_get_end_iter(log_buffer, &end);
        gtk_text_view_scroll_to_iter(GTK_TEXT_VIEW(log_text_view), &end, 0.0, FALSE, 0.0, 1.0);
    }
    g_string_free(buf, TRUE);
    if (err) g_error_free(err);
    return TRUE;
}

static gboolean ffmpeg_stderr_cb(GIOChannel *source, GIOCondition condition, gpointer user_data) {
    if (condition & (G_IO_HUP | G_IO_ERR)) {
        return FALSE;
    }
    GError *err = NULL;
    GString *buf = g_string_new(NULL);
    gchar tmp[1024];
    gsize bytes_read = 0;
    GIOStatus st = g_io_channel_read_chars(source, tmp, sizeof(tmp)-1, &bytes_read, &err);
    if (st == G_IO_STATUS_ERROR) {
        if (err) g_error_free(err);
        g_string_free(buf, TRUE);
        return FALSE;
    }
    if (bytes_read > 0) {
        tmp[bytes_read] = '\0';
        g_string_append(buf, tmp);
        gtk_text_buffer_insert_at_cursor(log_buffer, buf->str, -1);
        GtkTextIter end;
        gtk_text_buffer_get_end_iter(log_buffer, &end);
        gtk_text_view_scroll_to_iter(GTK_TEXT_VIEW(log_text_view), &end, 0.0, FALSE, 0.0, 1.0);
    }
    g_string_free(buf, TRUE);
    if (err) g_error_free(err);
    return TRUE;
}

static void on_stop_clicked(GtkButton *button, gpointer user_data) {
    // Kill ffmpeg
    if (ffmpeg_pid > 0) {
        kill(ffmpeg_pid, SIGKILL);
        g_spawn_close_pid(ffmpeg_pid);
        ffmpeg_pid = 0;
    } else {
        gchar *out = NULL;
        gchar *err = NULL;
        gint st = 0;
        g_spawn_command_line_sync("killall -9 ffmpeg", &out, &err, &st, NULL);
        g_free(out);
        g_free(err);
    }
    /* Clean up GIO channels and watches */
    if (ffmpeg_stdout_watch) {
        g_source_remove(ffmpeg_stdout_watch);
        ffmpeg_stdout_watch = 0;
    }
    if (ffmpeg_stderr_watch) {
        g_source_remove(ffmpeg_stderr_watch);
        ffmpeg_stderr_watch = 0;
    }
    if (ffmpeg_stdout_chan) {
        g_io_channel_shutdown(ffmpeg_stdout_chan, TRUE, NULL);
        g_io_channel_unref(ffmpeg_stdout_chan);
        ffmpeg_stdout_chan = NULL;
    }
    if (ffmpeg_stderr_chan) {
        g_io_channel_shutdown(ffmpeg_stderr_chan, TRUE, NULL);
        g_io_channel_unref(ffmpeg_stderr_chan);
        ffmpeg_stderr_chan = NULL;
    }
    // Re-enable UI
    update_start_button_state();
    gtk_widget_set_sensitive(stop_button, FALSE);
    /* Re-enable codec combos unless their 'Copy' checkboxes are active */
    if (!gtk_check_button_get_active(GTK_CHECK_BUTTON(copy_audio_check)))
        gtk_widget_set_sensitive(audio_combo, TRUE);
    else
        gtk_widget_set_sensitive(audio_combo, FALSE);
    if (!gtk_check_button_get_active(GTK_CHECK_BUTTON(copy_video_check)))
        gtk_widget_set_sensitive(video_combo, TRUE);
    else
        gtk_widget_set_sensitive(video_combo, FALSE);
    gtk_text_buffer_insert_at_cursor(log_buffer, "Conversion stopped.\n", -1);
}

/* Window close */
/* Adwaita dialog response handler: responses are string tokens like "accept"/"cancel" */
static void on_adw_exit_dialog_response(AdwDialog *dialog, const char *response, gpointer user_data)
{
    GtkWindow *window = GTK_WINDOW(user_data);
    (void)log_buffer; /* avoid debug-only access when log_buffer isn't used */
    if (!response) {
        adw_dialog_close(dialog);
        return;
    }
    if (g_strcmp0(response, "accept") == 0) {
        if (ffmpeg_pid > 0) {
            kill(ffmpeg_pid, SIGKILL);
            g_spawn_close_pid(ffmpeg_pid);
            ffmpeg_pid = 0;
        } else {
            gchar *out = NULL;
            gchar *err = NULL;
            gint st = 0;
            g_spawn_command_line_sync("killall -9 ffmpeg", &out, &err, &st, NULL);
            g_free(out);
            g_free(err);
        }
        if (window) gtk_window_destroy(window);
    }
    adw_dialog_close(dialog);
}

/* The quit dialog actions are handled by on_adw_exit_dialog_response. */

static gboolean on_window_close_request(GtkWindow *window, gpointer user_data) {
    /* If ffmpeg is running, show a confirmation dialog because quitting
     * will stop the conversion. If ffmpeg is not running, allow the
     * window to close immediately without prompting. */
    if (ffmpeg_pid > 0) {
        const char *title_text = "Quit baConverter";
    const char *desc_text = "A conversion is running. Do you want to quit and stop it?";
    (void)log_buffer;
        AdwDialog *d = adw_alert_dialog_new (title_text, desc_text);
        /* Add responses: 'cancel' for Cancel, 'accept' for Quit */
        adw_alert_dialog_add_responses (ADW_ALERT_DIALOG (d), "cancel", "_Cancel", "accept", "_Quit", NULL);
        g_signal_connect (d, "response", G_CALLBACK (on_adw_exit_dialog_response), window);
        adw_dialog_present (d, GTK_WIDGET (window));
        return TRUE; /* we've shown our own dialog and prevented immediate close */
    }

    /* No ffmpeg running: allow the window to close without confirmation. */
    (void)log_buffer;
    return FALSE;
}

void
activate (GtkApplication *app)
{
    GtkWidget *window;
    GtkWidget *box;
    GtkWidget *choose_button;
    GtkWidget *audio_box, *video_box;
    GtkWidget *scrolled;

    /* Create a GtkApplicationWindow tied to the application */
    window = gtk_application_window_new (app);
    gtk_window_set_title (GTK_WINDOW (window), "baConverter");
    gtk_window_set_default_size (GTK_WINDOW (window), 800, 600);
    g_signal_connect(window, "close-request", G_CALLBACK(on_window_close_request), NULL);

    /* Main box */
    box = gtk_box_new (GTK_ORIENTATION_VERTICAL, 8);
    gtk_widget_set_hexpand (box, TRUE);
    gtk_widget_set_vexpand (box, TRUE);
    gtk_widget_set_margin_top (box, 16);
    gtk_widget_set_margin_bottom (box, 16);
    gtk_widget_set_margin_start (box, 16);
    gtk_widget_set_margin_end (box, 16);

    /* Choose file and Batch buttons */
    GtkWidget *hchoose = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    choose_button = gtk_button_new_with_label ("Choose input file");
    g_signal_connect(choose_button, "clicked", G_CALLBACK(on_choose_file_clicked), window);
    gtk_box_append (GTK_BOX (hchoose), choose_button);
    GtkWidget *batch_button = gtk_button_new_with_label ("Batch");
    g_signal_connect(batch_button, "clicked", G_CALLBACK(on_batch_button_clicked), window);
    gtk_box_append (GTK_BOX (hchoose), batch_button);
    gtk_box_append (GTK_BOX (box), hchoose);

    /* Input label */
    input_label = gtk_label_new ("No input file selected");
    gtk_widget_set_halign (input_label, GTK_ALIGN_START);
    gtk_box_append (GTK_BOX (box), input_label);

    /* Output label */
    output_label = gtk_label_new ("No output file");
    gtk_widget_set_halign (output_label, GTK_ALIGN_START);
    gtk_box_append (GTK_BOX (box), output_label);

    /* Audio row */
    audio_box = gtk_box_new (GTK_ORIENTATION_HORIZONTAL, 8);
    copy_audio_check = gtk_check_button_new_with_label ("Copy audio");
    g_signal_connect(copy_audio_check, "toggled", G_CALLBACK(on_copy_audio_toggled), NULL);
    /* Initially disabled until an input file is selected */
    gtk_widget_set_sensitive(copy_audio_check, FALSE);
    gtk_box_append (GTK_BOX (audio_box), copy_audio_check);
    audio_combo = gtk_drop_down_new(NULL, 0);
    /* Initially disabled; will be enabled after an input file is selected */
    gtk_widget_set_sensitive(audio_combo, FALSE);
    /* Fixed width so both combos have equal length */
    gtk_widget_set_size_request(audio_combo, 250, -1);
    g_signal_connect(audio_combo, "notify::selected", G_CALLBACK(on_audio_combo_changed), NULL);
    gtk_box_append (GTK_BOX (audio_box), audio_combo);
    reset_audio = gtk_button_new_with_label ("Reset");
    g_signal_connect(reset_audio, "clicked", G_CALLBACK(on_reset_audio_clicked), NULL);
    /* Initially disabled; will be enabled/disabled after input selection */
    gtk_widget_set_sensitive(reset_audio, FALSE);
    gtk_box_append (GTK_BOX (audio_box), reset_audio);
    /* Separator and format combobox on the right */
    GtkWidget *sep_label_a = gtk_label_new("|");
    gtk_widget_set_margin_start(sep_label_a, 6);
    gtk_box_append(GTK_BOX(audio_box), sep_label_a);
    format_combo_audio = gtk_drop_down_new(NULL, 0);
    /* Initially disabled until an input file is selected */
    gtk_widget_set_size_request(format_combo_audio, 150, -1);
    gtk_widget_set_sensitive(format_combo_audio, FALSE);
    g_signal_connect(format_combo_audio, "notify::selected", G_CALLBACK(on_format_combo_changed_generic), NULL);
    gtk_box_append(GTK_BOX(audio_box), format_combo_audio);
    gtk_box_append (GTK_BOX (box), audio_box);

    /* Video row */
    video_box = gtk_box_new (GTK_ORIENTATION_HORIZONTAL, 8);
    copy_video_check = gtk_check_button_new_with_label ("Copy video");
    g_signal_connect(copy_video_check, "toggled", G_CALLBACK(on_copy_video_toggled), NULL);
    /* Initially disabled until an input file is selected */
    gtk_widget_set_sensitive(copy_video_check, FALSE);
    gtk_box_append (GTK_BOX (video_box), copy_video_check);
    video_combo = gtk_drop_down_new(NULL, 0);
    /* Initially disabled; will be enabled after an input file is selected */
    gtk_widget_set_sensitive(video_combo, FALSE);
    /* Fixed width so both combos have equal length */
    gtk_widget_set_size_request(video_combo, 250, -1);
    g_signal_connect(video_combo, "notify::selected", G_CALLBACK(on_video_combo_changed), NULL);
    gtk_box_append (GTK_BOX (video_box), video_combo);
    reset_video = gtk_button_new_with_label ("Reset");
    g_signal_connect(reset_video, "clicked", G_CALLBACK(on_reset_video_clicked), NULL);
    /* Initially disabled; will be enabled/disabled after input selection */
    gtk_widget_set_sensitive(reset_video, FALSE);
    gtk_box_append (GTK_BOX (video_box), reset_video);
    /* (format combobox moved to the audio row; no separate format on video row) */
    gtk_box_append (GTK_BOX (box), video_box);

    /* Start/Stop buttons */
    GtkWidget *button_box = gtk_box_new (GTK_ORIENTATION_HORIZONTAL, 8);
    start_button = gtk_button_new_with_label ("Start");
    /* Start disabled until an input file is selected */
    gtk_widget_set_sensitive(start_button, FALSE);
    g_signal_connect(start_button, "clicked", G_CALLBACK(on_start_clicked), NULL);
    gtk_box_append (GTK_BOX (button_box), start_button);
    stop_button = gtk_button_new_with_label ("Stop");
    /* Stop stays disabled until a conversion is running */
    gtk_widget_set_sensitive(stop_button, FALSE);
    g_signal_connect(stop_button, "clicked", G_CALLBACK(on_stop_clicked), NULL);
    gtk_box_append (GTK_BOX (button_box), stop_button);
    gtk_box_append (GTK_BOX (box), button_box);

    /* Log */
    scrolled = gtk_scrolled_window_new();
    gtk_widget_set_vexpand(scrolled, TRUE);
    log_text_view = gtk_text_view_new();
    log_buffer = gtk_text_view_get_buffer(GTK_TEXT_VIEW(log_text_view));
    gtk_text_view_set_editable(GTK_TEXT_VIEW(log_text_view), FALSE);
    gtk_scrolled_window_set_child(GTK_SCROLLED_WINDOW(scrolled), log_text_view);
    gtk_box_append (GTK_BOX (box), scrolled);

    gtk_window_set_child (GTK_WINDOW (window), box);

    /* Populate format dropdown from container_formats */
    if (container_formats) {
        if (format_model) { g_object_unref(format_model); format_model = NULL; }
        format_model = gtk_string_list_new(NULL);
        for (guint i = 0; i < container_formats->len; i++) {
            const char *f = g_ptr_array_index(container_formats, i);
            gtk_string_list_append(format_model, f);
        }
    gtk_drop_down_set_model(GTK_DROP_DOWN(format_combo_audio), (GListModel*)format_model);
        gtk_drop_down_set_selected(GTK_DROP_DOWN(format_combo_audio), 0);
    }

    /* Ensure every interactive widget is disabled on startup except the Choose button.
     * The Choose button (choose_button) remains enabled so the user can select an input file.
     */
    gtk_widget_set_sensitive(copy_audio_check, FALSE);
    gtk_widget_set_sensitive(audio_combo, FALSE);
    gtk_widget_set_sensitive(reset_audio, FALSE);
    gtk_widget_set_sensitive(format_combo_audio, FALSE);
    gtk_widget_set_sensitive(copy_video_check, FALSE);
    gtk_widget_set_sensitive(video_combo, FALSE);
    gtk_widget_set_sensitive(reset_video, FALSE);
    gtk_widget_set_sensitive(start_button, FALSE);
    gtk_widget_set_sensitive(stop_button, FALSE);
    /* Make log view non-interactive until an input is chosen */
    gtk_widget_set_sensitive(log_text_view, FALSE);
    if (scrolled) gtk_widget_set_sensitive(scrolled, FALSE);

    /* Present the window */
    gtk_window_present (GTK_WINDOW (window));
}

int
main (int argc, char **argv)
{
    GtkApplication *app;
    int status;

    g_set_prgname ("bac");

    /* Resolve ffmpeg and ffprobe paths */
    ffmpeg_path = g_find_program_in_path ("ffmpeg");
    ffprobe_path = g_find_program_in_path ("ffprobe");
    if (!ffmpeg_path)
        g_printerr ("ffmpeg not found in PATH\n");
    if (!ffprobe_path)
        g_printerr ("ffprobe not found in PATH\n");

    /* Gather available encoders from ffmpeg (if present) so we can populate
     * codec lists. */
    gather_ffmpeg_encoders(ffmpeg_path);

    /* Known container/format list (simple set). Kept separate so UI can
     * offer common choices regardless of ffmpeg availability. */
    container_formats = g_ptr_array_new_with_free_func(g_free);
    const char *formats[] = {"auto", "avi", "mp4", "mkv", "webm", "mov", "mpeg", "mp3", "flac", "wav", "ogg", NULL};
    for (int i = 0; formats[i] != NULL; i++)
        g_ptr_array_add(container_formats, g_strdup(formats[i]));

    app = gtk_application_new ("si.generacija.baconverter", G_APPLICATION_DEFAULT_FLAGS);

    g_signal_connect (app, "activate", G_CALLBACK (activate), NULL);

    status = g_application_run (G_APPLICATION (app), argc, argv);
    g_object_unref (app);

    if (audio_codecs) g_ptr_array_free(audio_codecs, TRUE);
    if (video_codecs) g_ptr_array_free(video_codecs, TRUE);

    return status;
}
