/* Điền hai giá trị từ Supabase → Project Settings → API. Khóa "anon" được thiết kế để công khai
   (an toàn nhờ đăng nhập + Row Level Security). TUYỆT ĐỐI KHÔNG dán khóa "service_role" vào đây. */
window.TYMEX_CONFIG = {
  SUPABASE_URL: "https://pqostminhxglclgrugzx.supabase.co",
  SUPABASE_ANON_KEY: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBxb3N0bWluaHhnbGNsZ3J1Z3p4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTIwMjk0NjMsImV4cCI6MjEwNzYwNTQ2M30.7w1D4CktSU_PrNFwFYAkqmmt2pweLq3yqgTgOU7udYA
",
  // Tên đăng nhập "tuyen" sẽ được đổi thành tuyen@tymex.app (Supabase Auth cần dạng email). Gõ đầy đủ email nếu muốn dùng email thật.
  USERNAME_DOMAIN: "tymex.app",
};
