/*
 * Futu Algo: Algorithmic High-Frequency Trading Framework
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 * Written by Bill Chan <billpwchan@hotmail.com>, 2021
 * Copyright (c)  billpwchan - All Rights Reserved
 */

create table stock_data
(
    id               integer not null
        constraint stock_data_pk
            primary key autoincrement,
    code             text    not null,
    time_key         text    not null,
    open_price       real,
    close_price      real,
    high_price       real,
    low_price        real,
    pe_ratio         real,
    turnover_rate    real,
    volume           integer,
    turnover         integer,
    change_rate      real,
    last_close_price real,
    k_type           text
);

create index stock_code
    on stock_data (code);

create index stock_code_interval
    on stock_data (code, k_type);

create unique index stock_data_id_uindex
    on stock_data (id);

create unique index stock_time
    on stock_data (code, time_key, k_type);

create table stock_pool
(
    id     integer not null
        constraint stock_pool_pk
            primary key autoincrement,
    date   text    not null,
    filter text    not null,
    code   text    not null
);

create unique index stock_pool_id_uindex
    on stock_pool (id);
