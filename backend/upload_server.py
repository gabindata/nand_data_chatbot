from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

import json
import os
import uuid
import math
import polars as pl


app = FastAPI(
    title="NAND Health Large File Upload Server"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================
# 설정
# =====================================

UPLOAD_DIR = "uploads"

PARQUET_DIR = "converted_parquet"

CHUNK_SIZE = 100 * 1024 * 1024


os.makedirs(
    UPLOAD_DIR,
    exist_ok=True
)

os.makedirs(
    PARQUET_DIR,
    exist_ok=True
)


# =====================================
# 1. 업로드 시작
# =====================================

@app.post("/upload/init")
async def init_upload(
    filename: str = Form(...),
    file_size: int = Form(...)
):

    if file_size <= 0:

        raise HTTPException(
            status_code=400,
            detail="파일 크기가 올바르지 않습니다."
        )


    # 고유한 업로드 ID 생성
    upload_id = str(uuid.uuid4())


    # 파일 확장자 유지
    safe_filename = os.path.basename(filename)


    # 업로드 폴더 생성
    upload_folder = os.path.join(
        UPLOAD_DIR,
        upload_id
    )

    os.makedirs(
        upload_folder,
        exist_ok=True
    )


    # 총 청크 개수 계산
    total_chunks = math.ceil(
        file_size / CHUNK_SIZE
    )


    return {
        "upload_id": upload_id,
        "filename": safe_filename,
        "file_size": file_size,
        "chunk_size": CHUNK_SIZE,
        "total_chunks": total_chunks
    }


# =====================================
# 2. 청크 업로드
# =====================================

@app.post("/upload/chunk")
async def upload_chunk(
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    chunk: UploadFile = File(...)
):

    upload_folder = os.path.join(
        UPLOAD_DIR,
        upload_id
    )


    if not os.path.exists(upload_folder):

        raise HTTPException(
            status_code=404,
            detail="존재하지 않는 업로드 ID입니다."
        )


    # 청크 파일 저장
    chunk_path = os.path.join(
        upload_folder,
        f"chunk_{chunk_index}"
    )


    # 1개 청크만 디스크에 저장
    with open(chunk_path, "wb") as buffer:

        while True:

            data = await chunk.read(
                1024 * 1024
            )

            if not data:

                break


            buffer.write(data)


    return {
        "message": "청크 업로드 완료",
        "upload_id": upload_id,
        "chunk_index": chunk_index
    }


# =====================================
# 3. 업로드 완료 및 파일 합치기
# =====================================

@app.post("/upload/complete")
async def complete_upload(
    upload_id: str = Form(...),
    filename: str = Form(...),
    total_chunks: int = Form(...)
):

    upload_folder = os.path.join(
        UPLOAD_DIR,
        upload_id
    )


    if not os.path.exists(upload_folder):

        raise HTTPException(
            status_code=404,
            detail="존재하지 않는 업로드 ID입니다."
        )


    safe_filename = os.path.basename(
        filename
    )


    final_path = os.path.join(
        UPLOAD_DIR,
        safe_filename
    )


    # 모든 청크가 존재하는지 확인
    for index in range(total_chunks):

        chunk_path = os.path.join(
            upload_folder,
            f"chunk_{index}"
        )


        if not os.path.exists(chunk_path):

            raise HTTPException(
                status_code=400,
                detail=f"{index}번 청크가 없습니다."
            )


    # 청크 순서대로 합치기
    with open(final_path, "wb") as final_file:

        for index in range(total_chunks):

            chunk_path = os.path.join(
                upload_folder,
                f"chunk_{index}"
            )


            with open(
                chunk_path,
                "rb"
            ) as chunk_file:

                while True:

                    data = chunk_file.read(
                        1024 * 1024
                    )


                    if not data:

                        break


                    final_file.write(data)


    # 임시 청크 삭제
    for index in range(total_chunks):

        chunk_path = os.path.join(
            upload_folder,
            f"chunk_{index}"
        )


        os.remove(chunk_path)


    os.rmdir(upload_folder)


    # =====================================
    # CSV → Parquet 자동 변환
    # =====================================

    if not safe_filename.lower().endswith(
        ".csv"
    ):

        raise HTTPException(
            status_code=400,
            detail="CSV 파일만 업로드할 수 있습니다."
        )


    parquet_file = os.path.join(
        PARQUET_DIR,
        "nand_health.parquet"
    )

    # 변환 도중 다른 사용자가 조회하다 반쪽짜리 parquet을 읽지 않도록
    # 임시 파일에 먼저 쓰고 완료 후 원자적으로 교체한다.
    tmp_parquet_file = parquet_file + ".tmp"

    try:

        pl.scan_csv(final_path).sink_parquet(
            tmp_parquet_file,
            compression="zstd"
        )

        os.replace(tmp_parquet_file, parquet_file)

    except Exception as e:

        if os.path.exists(tmp_parquet_file):
            os.remove(tmp_parquet_file)

        raise HTTPException(
            status_code=500,
            detail=f"CSV 변환 실패: {str(e)}"
        )

    # 원본 CSV는 대용량(수십 GB)일 수 있어 변환 성공 후 바로 정리한다.
    os.remove(final_path)

    # =====================================
    # 최근 업로드 파일 정보 저장
    # =====================================

    upload_info = {

        "filename": safe_filename,

        "file_path": os.path.abspath(
            parquet_file
        )

    }

    info_path = "upload_info.json"
    tmp_info_path = info_path + ".tmp"

    with open(
        tmp_info_path,
        "w",
        encoding="utf-8"
    ) as info_file:

        json.dump(
            upload_info,
            info_file,
            ensure_ascii=False,
            indent=4
        )

    os.replace(tmp_info_path, info_path)


    return {

        "message": "전체 파일 업로드 완료",

        "filename": safe_filename,

        "file_path": parquet_file

    }
# =====================================
# 업로드 상태 확인
# =====================================

@app.get("/upload/status/{upload_id}")
async def upload_status(upload_id: str):

    upload_folder = os.path.join(
        UPLOAD_DIR,
        upload_id
    )

    if not os.path.exists(upload_folder):

        raise HTTPException(
            status_code=404,
            detail="존재하지 않는 업로드 ID입니다."
        )


    uploaded_chunks = []

    for filename in os.listdir(upload_folder):

        if filename.startswith("chunk_"):

            chunk_index = int(
                filename.replace(
                    "chunk_",
                    ""
                )
            )

            uploaded_chunks.append(
                chunk_index
            )


    uploaded_chunks.sort()


    return {
        "upload_id": upload_id,
        "uploaded_chunks": uploaded_chunks,
        "uploaded_count": len(uploaded_chunks)
    }
# =====================================
# 최근 업로드 파일 정보 조회
# =====================================

@app.get("/upload/latest")
async def get_latest_upload():

    info_path = "upload_info.json"


    if not os.path.exists(info_path):

        raise HTTPException(
            status_code=404,
            detail="업로드된 파일이 없습니다."
        )


    with open(
        info_path,
        "r",
        encoding="utf-8"
    ) as info_file:

        upload_info = json.load(
            info_file
        )


    return upload_info