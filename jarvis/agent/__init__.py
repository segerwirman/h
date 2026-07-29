"""Native Jarvis agent core wrapped by the MK50 tier router.

Additive: tidak ada file lama yang diubah oleh package ini. Titik masuk:

    from jarvis.agent import dispatch
    dispatch.dispatch_async("riset X lalu simpan ringkasannya", on_done=...)

Semua subsistem opsional dan degradasi anggun: provider LLM belum
dikonfigurasi → ``dispatch.available()`` False dan caller melaporkan kondisi
itu dengan jelas. Tidak ada fallback ke Hermes CLI.
"""
