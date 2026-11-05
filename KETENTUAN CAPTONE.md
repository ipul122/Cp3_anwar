CAPSTONE PROJECT MODULE 3

General Information

Setelah menyelesaikan pembelajaran di modul 3, berarti siswa telah mempelajari dasar-dasar text representation, pengenalan LLM, sampai dengan pemanfaatan LLM untuk kasus Text-to-SQL. Capstone Project Module 3 ini bertujuan untuk mengukur seberapa jauh pemahaman siswa terhadap materi pembelajaran dengan mengaplikasikannya ke dalam suatu mini aplikasi.

Pengerjaan project ini akan melatih siswa untuk lebih memahami penyusunan alur RAG Agent sampai dengan integrasi dalam mini aplikasi menggunakan streamlit. Aplikasi wajib memiliki komponen yang menjadi syarat minimum. Siswa diharapkan dapat membuat aplikasi melebihi standar requirement yang sudah ditentukan.

Poin Penilaian

- Video Penjelasan : 25%
- Pembuatan Vector Database : 10%
- Pembuatan RAG Tool : 10%
- Pembuatan Agent : 20%
- Penyusunan Prompt : 10%
- Integrasi Dengan Streamlit : 25%

Detail Poin Penilaian

Siswa akan diberikan contoh flow dari tiap komponen penilaian untuk dijadikan basis minimum. Namun, jika siswa hanya dapat membuat aplikasi yang sesuai dengan contoh flow, maka nilai maksimum yang didapat adalah 75 untuk tiap komponennya.

Untuk mendapatkan poin lebih, maka siswa harus menambahkan kompleksitas sesuai kreativitas dari aplikasi yang dibuat. Kompleksitas yang dimaksud haruslah tetap sesuai dengan materi yang sudah dipelajari dan juga sesuai dengan petunjuk yang terdapat di dokumentasi ini.

Berikut ini adalah gambaran umum terkait komponen penilaian:

- Video Penjelasan (25%)
Siswa dapat menjelaskan tujuan, alur program dan kegunaan blok kode dari program dengan jelas dan terstruktur.

- Pembuatan Vector Database (10%)
Siswa dapat membuat vector database sebagai sumber informasi. Bagian ini mencakup mekanisme embedding data sampai insert data ke vector database. 

- Pembuatan RAG Tool (10%)
Siswa dapat membuat RAG tool yang nantinya akan dieksekusi oleh agent. RAG tool berisi skema untuk embedding query sampai dengan retrieve data ke vector database.

- Pembuatan Agent (20%)
Siswa dapat membuat agent yang memiliki RAG tool. Dalam membuat agent perlu diperhatikan juga komponen - komponen yang berkaitan seperti: state, chat history, dan parser (jika diperlukan).

- Penyusunan Prompt (10%)
Siswa dapat membuat prompt yang paling optimal supaya agent dapat melakukan tugasnya dengan baik dan mampu mengeksekusi tool yang diberikan. 

- Integrasi Model Dengan Streamlit (25%)
Siswa dapat mengintegrasikan model dan membuat mini aplikasi dengan streamlit, kemudian share project ke dalam Streamlit Community Cloud.

Waktu Pengerjaan

Lama waktu pengerjaan Capstone Project Module 3 adalah 15 hari kerja. Pengerjaan akan terhitung sejak H+1 setelah modul 1 selesai.

Metode Pengumpulan

Pengumpulan dilakukan dengan cara:
- Unggah video penjelasan project ke dalam cloud storage (Youtube, Google Drive, Dropbox) masing-masing siswa. Buka hak akses untuk publik.
- Video penjelasan maksimal berdurasi 15 menit dan wajib mengaktifkan kamera depan atau webcam, sehingga wajah siswa ada dalam rekaman video.
- Upload file Python project (.py) dan file pendukung lainnya (jika diperlukan) ke GitHub masing-masing siswa.
- Mengisi Google Forms yang telah disediakan oleh operasional untuk mencantumkan link GitHub dan cloud storage, serta link streamlit community cloud capstone project ini.
- Pastikan siswa menerima email konfirmasi bahwa siswa telah sukses melakukan pengisian dan pengumpulan Google Forms Capstone Project Module 3 yang dikirim secara otomatis oleh sistem. Cek folder spam apabila email tidak ada di folder inbox.

Catatan

- Untuk konteks Capstone Project Module 3 ini, peserta wajib membuat tiap komponen, hanya dengan Python sesuai dengan yang telah dipelajari di kelas.
- Dalam membangun agent dan pendefinisian tool harus menggunakan Langchain Framework (Langchain, Langgraph, Langfuse, dll).
- Gunakan OpenAI service untuk embedding model dan Qdrant Cloud sebagai sarana vector database dengan akun masing-masing.
- Pastikan anda tidak memasukkan data / informasi pribadi seperti api_key, password, dll ke dalam unggahan ataupun video. Untuk menghindari kesalahan tersebut silahkan mengacu pada source code yang diberikan.
- Jika siswa mengumpulkan Capstone Project Module 3 melewati tenggat waktu yang sudah ditentukan, maka akan ada pengurangan poin untuk nilai akhir sebagai berikut:
- Telat 1 detik sampai 24 jam: nilai akhir dikurangi 10 poin
- Telat 24 jam sampai 72 jam: nilai akhir dikurangi 20 poin
- Telat lebih dari 72 jam: nilai akhir menjadi 0
- Setelah project di-submit, dilarang untuk mengedit file project tersebut. Jika siswa melakukan edit/update, maka jam last update akan dianggap sebagai jam submit.
- Segala bentuk plagiarisme tidak akan ditoleransi dan mutlak diberikan nilai 0.




Ketentuan Minimum Capstone Project 3
Contoh aplikasi Capstone 3 : https://app-recipes.streamlit.app/
Ketentuan teknis chatbot-agent
1.	Peserta diharuskan membuat chatbot yang dapat terintegrasi dengan RAG proses untuk menjawab pertanyaan seputar data yang diberikan.
2.	Chatbot yang dibangun harus menggunakan arsitektur multi-agent seperti yang telah dipelajari di Module 3. Peserta bebas menentukan arsitektur multi-agent sesuai kebutuhan. Contoh code yang diberikan menggunakan arsitektur supervisor multi-agent as tools.
3.	Pembuatan agent dan workflow menggunakan Langchain dan Langgraph sebagai framework utamanya. Boleh menggunakan tools atau framework lainnya apabila hanya berupa support, bukan framework/ tools utama.
4.	Kebutuhan vector database menggunakan Qdrant Cloud dengan akun masing-masing.
5.	Chatbot-agent harus terintegrasi oleh chat history. Jadi apabila ditanya tentang detail atau konteks percakapan sebelumnya chatbot tetap bisa menjawab dengan baik. Jumlah history chat kebelakang yang mau di-maintain diserahkan kepada peserta tapi diusahakan minimal 3 percakapan kebelakang.
6.	Deploy aplikasi chatbot menggunakan Streamlit Cloud.
Ketentuan fitur dan tampilan Streamlit
1.	Aplikasi di-deploy harus dalam bentuk aplikasi streamlit pada Streamlit Cloud dengan link yang dapat diakses secara publik. Contoh: https://app-recipes.streamlit.app/ 
2.	Memiliki tampilan yang menunjukkan bahwa pertanyaan yang related terhadap document di vector DB akan dijawab dengan jawaban yang dihasilkan dari proses RAG, bukan dari default knowledge LLM atau bahkan halusinasi.
 
Contoh di atas merupakan bagian fitur streamlit yang disediakan untuk menunjukkan bahwa jawaban diambil dari Document (melalui RAG).
3.	Chatbot harus terintegrasi dengan chat history. Hal ini dapat ditunjukkan langsung dengan chat di streamlit seperti contoh berikut:
 
Kemudian konteks percakapan masih berlanjut
 
atau dapat dilengkapi dengan tombol untuk menampilkan chat history
 
4.	Tampilkan informasi penggunaan LLM (minimal penggunaan token)
 
