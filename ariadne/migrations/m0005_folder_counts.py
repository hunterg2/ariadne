"""A covering index for the sidebar's per-folder counts, so the one
GROUP BY folder query behind them never touches the table rows."""


def up(d):
    d.execute("CREATE INDEX IF NOT EXISTS idx_images_folder_counts "
              "ON images(folder, missing, stars, rejected, indexed_at)")
    d.execute("DROP INDEX IF EXISTS idx_images_folder")     # the new one covers it
