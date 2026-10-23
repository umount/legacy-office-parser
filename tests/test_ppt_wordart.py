"""Independent binary cases plus an original LibreOffice-produced PPT fixture.

The byte builders describe the wire format; they never call parser internals.
"""
from dataclasses import replace
from struct import pack

import pytest

from legacy_office_parser.errors import InvalidDocumentError, LimitExceededError
from legacy_office_parser.limits import Limits
from test_ppt import File, atom, container, document, persist, run, slide, text


def props(entries, typ=0xf00b, version=3):
    fixed, complex_data = bytearray(), bytearray()
    for pid, value in entries:
        if isinstance(value, bytes):
            fixed.extend(pack('<HI', pid | 0x8000, len(value)))
            complex_data.extend(value)
        else:
            fixed.extend(pack('<HI', pid, value))
    return atom(typ, fixed + complex_data, version, len(entries))


def wordart(value, bid=False):
    return props([(0xc0 | (0x4000 if bid else 0), (value + '\0').encode('utf-16-le'))])


def shape(value):
    return container(0xf004, value)


def drawing(value):
    return atom(1036, container(0xf002, value))


def file(value, outline=b''):
    return File().edit({1: document(persist(2, 200) + outline), 2: slide(drawing(value))})


def test_geometry_only_group_unicode_and_title_contract(monkeypatch):
    value = 'Привет\r\n世界\v😀\fEnd'
    result = run(monkeypatch, file(container(0xf003, shape(wordart(value, True))), text('Title', 0)))
    assert result.slides[0].title == 'Title'
    assert result.slides[0].text == 'Привет\n世界\n😀\nEnd'


@pytest.mark.parametrize('reverse', [False, True])
def test_local_fallback_not_duplicated_and_other_shapes_preserved(monkeypatch, reverse):
    native = atom(0xf00d, text('same'))
    geo = wordart('same')
    body = shape(native + geo if reverse else geo + native) + shape(geo)
    assert run(monkeypatch, file(body)).slides[0].text == 'same\nsame'


def test_outline_reference_only_deduplicates_its_own_shape(monkeypatch):
    body = shape(wordart('same') + atom(0xf00d, atom(3998, pack('<I', 0))))
    body += shape(wordart('same'))
    result = run(monkeypatch, file(body, text('same', 0)))
    assert result.slides[0].title == 'same'
    assert result.slides[0].text == 'same'


def test_distinct_attached_text_is_not_lost(monkeypatch):
    body = shape(wordart('art') + atom(0xf00d, text('attached')))
    assert run(monkeypatch, file(body)).slides[0].text == 'attached\nart'


def test_unknown_complex_offsets_and_metadata_are_not_text(monkeypatch):
    properties = props([(0x80, b'ignore'), (0xc0, 'visible\0'.encode('utf-16-le')),
                        (0xc5, 'font\0'.encode('utf-16-le')), (0x380, b'name')])
    assert run(monkeypatch, file(shape(properties))).slides[0].text == 'visible'


def test_alternate_xml_not_a_second_text_source(monkeypatch):
    alt = props([(0x3a9, b'PK not interpreted as text')], typ=0xf122)
    result = run(monkeypatch, file(shape(wordart('native') + alt) + shape(alt)))
    assert result.slides[0].text == 'native'
    assert len(result.warnings) == 1
    assert 'alternate OfficeArt XML' in result.warnings[0]


def test_no_property_scan_outside_live_shapes(monkeypatch):
    f = file(shape(wordart('old')))
    f.edit({2: slide(drawing(shape(wordart('current')))),
            3: slide(drawing(shape(wordart('unused slide')))),
            4: container(1016, drawing(shape(wordart('unused master'))))})
    f.put(slide(drawing(shape(wordart('appended stale')))))
    assert run(monkeypatch, f).slides[0].text == 'current'
    # Dg-level properties and unknown containers are not shape instances.
    body = wordart('default') + container(0xf000, shape(wordart('not live')))
    assert run(monkeypatch, file(body)).text == ''


def test_linked_notes_only(monkeypatch):
    def note(sid, value):
        return container(1008, atom(1009, pack('<IHH', sid, 0, 0), 1)
                         + drawing(shape(wordart(value))))
    f = File().edit({1: document(persist(2, 200), persist(3, 300) + persist(4, 400)),
                     2: slide(notes=300), 3: note(200, 'notes art'), 4: note(200, 'dead')})
    assert run(monkeypatch, f).slides[0].notes == 'notes art'


@pytest.mark.parametrize('raw', [b'', b'x', b'x\0', b'\0\xd8\0\0', b'\0\xdc\0\0', b'a\0\0\0b\0\0\0'])
def test_bad_geometry_utf16_and_terminator(monkeypatch, raw):
    with pytest.raises(InvalidDocumentError):
        run(monkeypatch, file(shape(props([(0xc0, raw)]))))


@pytest.mark.parametrize('bad', [
    atom(0xf00b, b'', 3, 1),
    atom(0xf00b, pack('<HI', 0x80c0, 0xffffffff), 3, 1),
    atom(0xf00b, pack('<HI', 0x8080, 0xffffffff) + pack('<HI', 0x80c0, 2) + b'\0\0', 3, 2),
    props([(0xc0, 4)]),
    props([(0xc0, b'\0\0'), (0xc0, b'\0\0')]),
    props([(0xc0, b'\0\0')], version=0),
    atom(0xf00b, b'junk', 3, 0),
    wordart('a') + wordart('b'),
])
def test_malformed_properties_fail_closed(monkeypatch, bad):
    with pytest.raises(InvalidDocumentError):
        run(monkeypatch, file(shape(bad)))


def test_empty_and_default_geometry(monkeypatch):
    assert run(monkeypatch, file(shape(wordart('')) + shape(props([(0xc0, 0)])))).text == ''


@pytest.mark.parametrize('pid,width,payload', [(0x145, -16, b'abcd'), (0x146, 2, b'ab')])
@pytest.mark.parametrize('includes_header', [True, False])
def test_legacy_array_lengths(monkeypatch, pid, width, payload, includes_header):
    array = pack('<HHh', 1, 1, width) + payload
    geo = 'after array\0'.encode('utf-16-le')
    # Deliberately not sorted: complex order must follow table order.
    raw = pack('<HIHI', pid | 0x8000, len(array) if includes_header else len(payload),
               0x80c0, len(geo)) + array + geo
    assert run(monkeypatch, file(shape(atom(0xf00b, raw, 3, 2)))).text == 'after array'


def test_shared_utf16_budget_includes_terminator_and_surrogates(monkeypatch):
    f = file(shape(wordart('😀')))
    assert run(monkeypatch, f, replace(Limits(), max_text_chars=3)).text == '😀'
    with pytest.raises(LimitExceededError, match='text limit'):
        run(monkeypatch, f, replace(Limits(), max_text_chars=2))
    # Even a suppressed same-shape representation consumes decode budget.
    f = file(shape(wordart('abc') + atom(0xf00d, text('abc'))))
    with pytest.raises(LimitExceededError, match='text limit'):
        run(monkeypatch, f, replace(Limits(), max_text_chars=6))


def test_property_count_and_depth_budgets(monkeypatch):
    f = file(shape(props([(i, 0) for i in range(100)])))
    with pytest.raises(LimitExceededError, match='record'):
        run(monkeypatch, f, replace(Limits(), max_records=50))
    f = file(container(0xf003, container(0xf003, shape(wordart('a')))))
    with pytest.raises(LimitExceededError, match='depth'):
        run(monkeypatch, f, replace(Limits(), max_depth=4))


def test_original_libreoffice_ppt_geometry_only(monkeypatch):
    import base64
    import hashlib
    import zlib
    from legacy_office_parser import ppt

    raw = zlib.decompress(base64.b85decode(_ORIGINAL_PPT))
    assert hashlib.sha256(raw).hexdigest() == '2d0a5dac9bd229a57e382a075bbe362bdf291e5933298593029d9d54eddc007d'
    result = ppt.parse_ppt_bytes(raw, Limits())
    # Authored literals, also independently read back through LibreOffice UNO.
    assert len(result.slides) == 1
    assert result.slides[0].title == ''
    assert result.slides[0].text == 'WordArt original / Привет 世界\nRepeated WordArt\nRepeated WordArt'
    assert result.slides[0].notes == ''
    # Demonstrate that native TextChars/Bytes atoms cannot supply this fixture.
    monkeypatch.setattr(ppt._Parser, 'shape_properties', lambda self, rec: None)
    assert ppt.parse_ppt_bytes(raw, Limits()).text == ''


# Original, unmodified LibreOffice 7.4.7.2 PPT, generated for this regression.
# zlib/base85 keeps the real CFB fixture inside the user-authorized test file.
# Provenance and reproducible generation recipe: docs/PPT.md.
_ORIGINAL_PPT = (
    b'c-riJ1%MpKmG-P8+cG3l9K0l#=yJ&=mpF+NhcCG>-G#}vES7e)q+Mx+mYHp7nHj~*3`@hf%*@O@@PF0a)7wL<71)20d!OeU&CWDb'
    b'SH1e)dsWqKlko$MS*JhVBy+-l$rj42wg+YROTK#md~u=h$5NSW0sip<tu~v@zRk<vE8wf(YvAkP8=#HwcL|H|uT|iEXsi2$wq6WA'
    b'2tEWp3_b$B4}3qkgf{`%2f#<c4}u>8KMa0Eu!)c1-+uu=4t@gsB>1o3r@&8x%fNpFKLh?d_*w9C;D3Oh2fqORC-_D1OW<SRm%*=q'
    b'Uj-irzXpCCd;<Ii_)YLz;J3l=fZqkb$Jw(?_I>aN;D3WZ1b+nn82kzNQ}Act&%s}SzXX2;{u=xr@PEPIfWHNQ2mT)X1NcYqPvD=y'
    b'zkq)Q{{}t@J_SAvE(f0hSAZ+QRp4rH4Y(Fu2d)P<fZm`FxDoUP{Xl;(01N~-fk9v}xEb66hJahaZQyor2e=d51wISz2A>0;2VY=)'
    b'7<>tQlPh~L{@aGO_&JWd4aa&`c02fp>^_ISJ)eE7^W1K}p!47P`K^+^zX*Rz`@fas@t+=EXyt_u@iw$H?3E2Ezc+s1&2HHd+2#N2'
    b'WZM4QKQH@3@J{cLKLq;)ZCm!;Z#&zP7as=P1;&?rR`4CGbE8_eeUAB=(S<C``04hL5O19IuUoxC7JIa1RtDE1ux}QW>B~~T@`<G}'
    b'35#W4dTi<h)A#$FzGIsFF(Hoe5_}rlx62}v<>KE(!tuT!{Qei=ceWoZ<2n1e1V6d@55NA|>R<l#*FWQaeZ>CFuYU9E-~I2OCCC1;'
    b';76W=*ZB#&*pK0Xz6;Ow4S2Yp!<&5<e}5U@e+|EX9iM)TPd|re`ZB!U<Jj(TZ1HXU_G5UwZ^6@jms58BxQlM1_Ls;y7yjZtc5Ph?'
    b'*)<wa8KZFW$#Ckw|2Tim3xsRs+nb9By_U#^7yf7g^TVnok8r-Yc*!F1m}L*Na-S|P`59Mde(+n~@KMWf&ED`$%Q(NY3EnSgUZuQ$'
    b'=~CfXKZb|$!+wExY;X53T_zmsXDEw5j`cTq&1LZ5tTbD1?^xizB}=)u*GEv|M`gSYA71j1prZ?94=!fWM$VG=dohKzS$>EZ>NCrD'
    b'k1w;bsKBn>%UFeTwQaKv$avf4kIHXpdtn*&{h-UfrCw~$x%P2ApJ@SW!P`5};KDTv=icY4%z2-s_r1Kx(>_aN4=)Pk<H^C-`8pkB'
    b'aoxhDyf6BYV9#D+UGj11Lcv!p68LGE*Px7xqaGe)dh&{w?2=9P8dsY)y_TY1=X&9f#Wt_S*xzdbj<fhjvQG^y<@aCAeq-NFKmtB3'
    b'8(i{9t}G)9KO}PzxR-ewH$Cv*UhKR!`!<Unanwa@Gre#luTq?zabH>%enSWoH_Y+xv5(4R)#!$!W}EF8C(|t4n^|a=!Oe?j|7O4a'
    b'=wWuc2Nr#w`;|Y(5l}V9zwXZQX{RE4%@+B;gra%+mmTgAG~*YhY_>~oip+{AEi$`=AIhqh@U>RWsmJ>e|Nq|QyC2}v99v|OROP(*'
    b'f4=Ip&3$gR@sfEh`h)NhMSSUAL|^=&yBG3SF}d)2A7Iunuu$|WZv5jK+28}qc)j3F>gAXDA9P8wC!WyBbUK^t%$YOdcGyzfmi=Q('
    b';y<u&;^X5b$J24!`1m{_V~2bq=?UIkaZH=e$K||FJn;ngZ(Us-SBBsI_P4U`?rx9eW5-}+K?!BKxw#&<W53CK`0~k;JYVk<Nj6!M'
    b'O~)ONU9ZfeMtaRdBOmjiU0!o&<YOK*(rXTlyw!Q!Y2;%bG}3DhjkNExbWYC^jx8(asFh`NDEfX6werb1JjYcJweqn!&Qt86Rz5U`'
    b'=jifKEB1Ys%~2~GxG{!VTUj91ialF;#A9jseWkVHejnHKNo!@k=aJTm`+cOf!tW!k73X~@%5b;OA5bgxf={r$AamQ(E4kWufZKbS'
    b'@C(1KdnIw)c7ey^vg>!;cA>}Pvg>x-c9F2Hd&O|vcFjDlQYN{|$8O^)AG?jKeC#%^^0C{vN`BkTPFK0asV6dhm~Bg$Lt8F!>VY2;'
    b'db)kvPfD)R-En8HlFu6LSLyD!vscMSvG%K6;?$!*B=l&<ZD0OBag|GCk1T3_fNi~Cu=)Y!=@t(z7V@h57qRab4hC|+FB;@C@COH%'
    b'x{1LS$R6VMV*%fNGGTi!HZskB@3n|e&p+t(@SqPj`ss!3UY33K@!i~P1wUWG&sgwt7W}M*O!gKR!`;Mz7a@<3ae2fyy!XlSyjW@S'
    b'y|l^C$jZ48uY!BGA!2?|$S<%pclL1E54^%Z+O%Ma>;ppS3m#tVkSDxva5wi?#**3GJ#)z~xN+$~<h$!-0chcE$eEWRXWf8rwsC*^'
    b';xG0u`#Vth>@C~H{py3QL%1B9jSFWlxnCGzXE?&;rk@p~S5{xYS}<E*3p~_UtE9e`1-q{=*<IJy&la-!TK=$eec8t%SbZgX&DNKf'
    b'P+vdsnqPedBj4Y~Z5K30oxM-?XMDdN-vr?Z%aE5i?)4kI?*Id_<zH}QKkRv{?S8?XJA^CAt+w<-X>PsUpYiRkd2Ppk4!Y&G%vQcA'
    b'%);>VIbJe8!~HN9Gw}Hr|Napn$KvfN+rgf`A?be$J=oK}uid);-Mu|sc;p9O3m-W8K6m}^0l}W$l=Qzvf;}w|=AN>+5lTLd^V<B7'
    b'%pP&r#~mLK=ERuNO-g$3ktOdJ_T&B6gWOLCmV8_|$9-HJ#-bw@?Xc)2^FF@rz9*@>MIP#I!`I)Nx_f@{Q%l{~-Gf5ih0a-b|1n#4'
    b'yB^}|!E^0R&!hG}C7k7cx3!mhKVO62lGNaRp49(|_ofEbABgy<`x;y<)Zp8<Rf7xWsKLs6Vt>Dr&DI|C!)zcsM)vR^n^}FC>*BAl'
    b'@e^TuEyin0QIagyEB?*Dp_U%So^0@Ev24*oW+6XZ=!J7Ho#%+h5=0cc9$=*%vX2xA<86;D`i>AOJpKTSclbzwUD*SR`A9)^|7}DH'
    b'i)SN+E0U}ATI|8|J@H;d3bF-n%RcaE?ZfVD<vzhy9+B9}0ykH%z{3^n`^I}=?Jqr2>vetUUq9yV3htld3cfG(79Or(!#CfHD`0qZ'
    b'@gKb0UBN@b6@=d-Z!tBG-ufBg91nQZyG9{G{%@(*@KA@J{nmR^hi^TU^r-tfw0qphd!~7l_p}zJmUy2hHJC>&F1YJjw0?|P;_p5_'
    b'm+!q-mN@;cS>pYk^yu5~O&u~zbYF*y@3|#b-qTwAl|<E<k7Hi=HF)92UHotTbzk`3@Ql3@|0}yg|J%RtSNF}%U@*LIsbucUi@zRd'
    b'*TSW;*(sI<+)6N3ZpYahwxWyqZvTb6?_Rf%%@y;$o2&0fc;9{h!rSoOkIee+Y5bf2py0b7;Vtc_u(V>%iWZ1|IX9QB0?X(2E8yx?'
    b'p3BvTO!iBg?U!D=@WZdX9!HbE<n;rT>=mz&3?u3{Y|Z21{NdcT$L1A(xPX=NNiK`rz|B=}<MK^5XT6cjwb;z{GTB$bPcQn>qVFvF'
    b'`l4?x`pKeYvXA`kH{00?Ge6lnWMLs(2I|M<o{lrqyj3f_6kb35@PP%a2AU-`us~7+S6ph~Gw)dq{0Y~v8C=Wd)+{S_tdsd)=^yW7'
    b'SNf&<ov(D^Ki!qqE@oGH;X%#^NqRmvt^COB%(gw+X76_&ZNL4&<zB2O?fKxJIL)}it!7xw{r3m__ZQjMxOJ9$KlpX-_nxn?GEJ>4'
    b'^m_agzhtY1zhqauPs@HbbU(Mv=ZBU#_1uL{tJNOmdhZX0*lN-rdHrOFwUpO`!a?$6t_SgQI*5H}(&Zq0X?{HPA<3E^X(@gv``plD'
    b'{E8lK?%zxBrL*f{zCXn4m)Do<V@tnxv(H1f*auqoCH}X;g}q+0`3(DUp<A8&Ca05$Uc635GT$KR<U(OR1k=ecc-@9hE}hj$wiY$}'
    b'5kV)H3VjC_^)aWuQ_ju!^R_L`N*;Z*&TUrmuyFiH$?+Em$Irp>zwdPX`T23yCXQubdBu&TfBTrbF~LXX$Sb5ilyg`feJJyuv79Hp'
    b'+g>G;g?yBs{pZ&j{0@x}`4L>nr{L?^LTA|+zfu8bxb{BYuK)5m{#rOA=2ld{H}JH6j+LeHjf~-`-}^2-8nsyVrO%(OVs&;60m=jR'
    b'MJGbv`IXQg{vz1J8lg=Bh4tdQgmvPtOV+=AO8ERW;W&28_4$j9>P@@X)_JkD*^i?fOi30CYxCH_mT~qZL@l}Z&$&*PKp+qZ1OkCT'
    b'AP@)y0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2m}IwKp+qZ'
    b'1OkCTAP@)y0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2m}Iw'
    b'Kp+qZ1OkCTAP@)y!g~jc2fihf$=(Lv0r!A=!B8*^3<o2?NH7YF24lcjFb<3d6Tn0;2}}l4z*H~|Ob0W-OfU<~26MoD;C}D`cn~}U'
    b'9tMwqN5Ny@aqt9q5<CT-2G4+J!E@kw@B(-dyaZkbuYgy<Yv6V826z+91@pjsumCIs<)8vof+|oAYCtWh1NEQ*G=e6u2rLFmz*4Xb'
    b'EC(yVO0Wv725Z1tunw#T8^A`e32X*iz*evgYzI5QPOuB?27AC>un+792f#sa2pk4Sz)^4v90w=BNpK3B24_GsXaTLD4U~D|1ug&='
    b'f{VcW!27`mz{TK$;6vcU;3MGs!1seoz@^{^z(>Ikf*%4u41NUsDEKk(U%-!pp8!7z{ww$?@YCQj@ZZ4Cfd3AD7W^FeAK>S~FM$6E'
    b'ei8f<_!#(Q@GIa~!N<X`fnNuo0KWl#6Z{tVZSXtbcfs$0{{?;@`~mpi;19tcfj<U+0{#^I8TfPX7vL|!UxB{{{|EeE@HgOZ!QX+u'
    b'2mb*65&RSQXYeoJU%|hDPl8W@PlL<BXTTNUN^ljp8e9Xe1=oS=!404{=mTy9eL+9a9}EBk!A)Qg7z}O(w}2twR&X1*9ozx#1b2bY'
    b'g1f=zz~{jiz!$-nz?Z>Sz*oW7z}LYyz&F9Sz_-D7z&+qzFcb^}!@&qJ5{v?)!5A<Wj05Ar1TYay0+YcMFcnM#)4>cd6U+j$!5nZO'
    b'xF0+K9t018hruJ@QScae96SM@1W$pd!871l@Emv^yZ~MVFM*fAE8tb|8h9PN0p0|2!8|Y@EC35ZIj8`YpbAuj8c+-BKs{&xji3oE'
    b'0*k>CuoNr<%fSk;608EN!5Xj@tOM)82Cxxq0-M1WuoY|r+rbX76YK)J!5**|>;wD30dNo;0*Ap7a1<N^$H5735}X33!5PpDT0kpk'
    b'17!=)|G@>|LU0jyA9z3b0Js=@5PS%H7<>eLANYQ73Ahye0Qe~QLGVN1hry449|b=K{tNhV@Dt!C!G8rm1%4V_2L2oP8Svl1&w`%='
    b'{{#Fy_yzDk!7qYe0v`jv41NXtD)>0~HSp`;6W}+%Z-U<fzYTr|{4V%C@V~(CgFgWO8~h>oBk;%IPr#poKLdXb{sR0Z_$%<&;QxUC'
    b'3;qWDE%-a|_uwDEKZ1V({|x>G{44l3@Ja9~@M&;4_zbuLTnVlMSA%Q7wct8%J-7k%27SPdpfBhL`hx*rAh-z(0)xTL;1)0h+zM_3'
    b'w}U&to!~C;S#US_9QZu=0{9~M68JLs3ivAc8u&W+2KXlU7Wg*!4!8&03x<MWU^o~7MuJgbG#CTMf^lFxm;fe%NnkRV0;Ym#U^<uq'
    b'W`bE@HkbqM1NVamz=Pl+@Gy7;JPIBIkAo+`li(@vG<XI)3!VedgBQSy;3e=fcm=!)UIVX#H^7@<E|>@Ag9TtAC<hgw5>$a|Py=c~'
    b'9jFHlpb<2IMPM;l0+xbhU^!R;R)SSvHCO}If^}d$*Z?+yO<*(F0=9x}U_00Wc7k1CH`oLAf_-2=H~<cUL*Ott0*-=X;5aw|PJ&b5'
    b'G&lpAK?`UFZJ=x+`aie;TnH`#?*s1#9{?AF4}uSY4}*_@?*rctE&-Q<9{?W(KL~yZ{4n?t@T1_zz<&Wh4t@gsB>1o3r@&8x%fNpF'
    b'KLh?d_*w9C;D3Oh2fqORC-_D1OW<SRm%*=qUj-irzXpCCd;<Ii_)YLz;J3l=fZqkb2mTlMeeeh1e}g{+e+2#*{0aC|@Mqx9!C!#C'
    b'1b+qo8vGydf5G2?zXg8>{vP}T_($+h;Ge<2fPV%520jTs1wIWf2cH2~fGfdO;A(IUxE5Rot_L@O-k=Y-5%dN9Kz}d*3<NiUL0~Yr'
    b'8QcPffLp<B;C65axD(t3J`3&!p97x<UjVI$?_U!BB@hS%0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2m}Iw'
    b'Kp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-'
    b'2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YU'
    b'fj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}Vq<G^aQ3Lh*Mi`gu`3%}WaB@hS%'
    b'0)aqyw*wNqTO<&_oac_>?(^Akj)UCp?gYX=X#C$(SKLvq>Z&qyR_X@Y>g?e^S^j&Qg-PVgNqodV-Tr#7^ww&}ZL2PqHu5igp3m;~'
    b'pX{f@iyg#l|9~TKFY!<O#HXlMHwU+WBV2`L9+xm%cz!SO>=yA_X3uL8%EKMkJcBR!cmCMi*VxQ5`+gS<<m!f;{E^sL^S1=oW8Pas'
    b'qW;VG0@#JaD9XI+)}euT)3VqHWIR~AeS6-7nc<0jkn1(vm)5!Lg#XiQHmj0D)N$ULq(EiN`l6$I#ql2pQMeaoBh|6nJ%T5(a$735'
    b'2JcB)EmED~>djSTBnOmMICc>mYex9Y+kpKDo~qsPyyDR;4hQFcvIxq<S(hL$mb>q^Y<KPuR!N=Aewep@@}}-o?Q`tTpHu2M=6NlW'
    b'CNSTnc1aI4Pgiw&8*_b7>_@lNBGTR6`8cbqozG8I1TV%_zP&TtPW=<!?VK0=VQ!mo&_J_P2dwip0B7Sd&&=qvb{o@!jal3DDS@S@'
    b'qS)b>FOwYKMO3*k&+IlB^C)o+VU=Tu<vF@@xdhH)XScCB#D4Z`w0keJ8)b9wp106a=L)xQ-N$;HfwA<|_6~kq%45CPp_+r#Sgq5O'
    b';}au86C;BY!vo_(edELZ_6U3q4Hv3@W^%l*sgi&7HkS9)6%BSY;#ap9=y+bP=54l#(V@QPs`gTOqxxL+)vVIf(IqFsOOA&Xp9m{C'
    b'8Bu;Np)UVui~ee7rFOWx73MlyCz7NHADgt7i;jntor^C$6H|6Rd3s`O?!sHRy=JDT2ixjei}D(jXKSwSD?1y@3UDg2>}-7XwVVd!'
    b'nT|5~a90a9!^Zthm5u5PEynB3hU;BbI{tv>>B-ij{O)Rfca5>T#?;$TW}cqnYT!0pfK!XWa#(YW3{8%WOpT9DjSWjW?DX{16zXAS'
    b'dd6azm-RaIdb?PV;@?97pBft~zmQsaIlby?cIA~!nBpx*QJj>Y|8uCbxvjW>8;#L*R;ZeESI38X-Npv|{;-6x!QSDn=7HAQzNU)4'
    b'#<JeVvi{~um^6$QKTS_gNR7l*5@ATX%xCp!L59q&y5xY;Q;|}m#XAy&ndzzNsY%!!^i|UJ-2_Dr-`}qNdx-A%=$AKH;VP^wKsK|I'
    b'&4}BIzY4-DT(4zna)RqbW2g#jFO5I>vf)<<%V0;tP-i1vBi${d{oOOulVUBgv)iu%l`uBYgN;$uofYa<(~V~R6}%u&ZN+)rHHQ9{'
    b'Y8(xx69)&JyP;kBW~L_5YHdY%jjFR%SJELnr6(hycu>ExvvIY#hguBR23l%ZPoEsGxRhRYCa(N^Qt|Qd?rH;noVzqy3s<WHtu>mA'
    b'UHYtN@iJsRtIOP}PT2xMV;i6vU0TpdKg-T1DWcYCl7m!n8#Rf6ngoAU;-;<|qubqQo7Kt;uf0rBaxzkzzC#_qF@Mif1>vhzNt<<<'
    b'yN!q5C_c8g=<wUR>=)E2A@ZmVd3&BjimFZ7Vm$C#ec`F`p?==!OU(lnsEl5vO9|8^`KpsQ+qZF}|2$BDChaAC_VcO)e-uCwv9cg+'
    b'r7|H<le$ft@ho2I)NRUyO$8Ba^TSqYGj_EaZ|ZVhRz$2&#rY^BR~ZhxCLX%-O3ux<pVTJ#BZ*eU`IcWufwA#5Y_YrVTY!(w&Fn(Z'
    b'*UHW&Xj8Z9v!63$?=Fb;ZPH)oPXtGx&3ZwXu~V1zoH})DZQhYNEI~9m=s=_DT=}^~M0aqkMTg%kI`VeOiLm11VeKV_Voeh6s4KCm'
    b'g8~<XuhJ#?X%qd_vFi-`UlF_it%foLrGn;EUd~V@1ZWcdVe0vz%jNNbHF?Jon>o62roafX>gA`<cMLf%s1gJ6L!ZeHT~QFehS@6j'
    b'o)@+%Z|`z>j1Rg`(b0FRujjOvDiBe)#sj?m8`6S|O#l5$PsdD-kG7W-R9r|h9(+Tcx?K?$pokAdN5BhRwd6!-#l=*_MZFEBP%xY0'
    b'0D@DzIz2Hy&{hX`)~vf+mw&ACQW}mAiQ|M0Ayym;hC{U)Z}ij_jr6vgIs11b7qH=h9t3G{uVrUqO^4ppq;5rdP%u?eur~8q<DoYZ'
    b'_%&%S4z}0vAtF3!#pQJ4!Pk)8pxBCdT*apRC|_ZMgX=O7aMO{u(VNuCL5irgd3&EhrJ=LmeEaFz{9}T<<hF#EAnHS}H12;HZNw@('
    b'Y*l{vYP<>}*Wr~PwmL6#CHpe;8D*>w+NJDFOtbC^!fDq!pBfv%@ga0fdE&eaL!T~;Tnov<H?SPTfmd1YPT5)*<&7fgb6%*pk|mE?'
    b't4;FNCHc$4m*cS9C7AC{{4Jc-b-_Ylx5kVunnb_CsP)G5%}55-Nx{916{3%DXc6uYUa9I8XHaiN**g$FD3iBB{Y+Wg4Qat>o&J_u'
    b'n|(8zixV8_?SOtNW7Z?&&?g6Adt4L>W0trKVRXuBofz(iK|+?1pR$7|Y($Iqx76^xPt^bN3rX4pUt{KWWBL|-=CjCU=8FH}FV4m*'
    b'B3J8EgG^c5(CNxArlMO-Pfl8_Vr;-hN5=-cyQ{RO!*8Qyb*aJFm|bJ)CfK3$irPyH<<Z{gN2m==f^X5Wy`CJ9Q*mrU^diJ{V}m{V'
    b'{jaEFH<&WF>Qe#~(HmM#H$|NpAM91e`y0|W8PYdv;x`~Unp^)l)9r;VsbbednqWVwcwfW*m!bScN8V8-hs^Ck2=mnck?vOXW!MH('
    b'RG+%3=-3{M#p*i#ENY`v`H^l{-#Cb<iFL!YU=`w=^qoz*%X|po)N#fK`$|s5DC2xJ@jluFA4T*!xN-!LU6mRHlS7?Nd=T5$P})&i'
    b'SYLR&=<r+esCDwN<prV33!=O$u4E&cca8s<{%3@s?<3AZ2m~q9=e$&YF1{}BP_yPjv-VPh{AAUYjN)T^6mh-?ftZ_1@P{F_6&E^O'
    b'o!yrDo2x4>r06ntK@;Q=EA#d|#hg*{793xf{XBv$bYV@}HmG-D<hs0fo>WAy)g}i+U15-;eVq=PX|vT8oKPhMvYJWsRYt9WWWkSA'
    b'UCpe^JB&CPX&1y+zwc#vtRG5_ps`th4Z)i_ZasQ8<OOk5tKnK_nF2Bb?d2P;uc^EsVl}!Lx{^L+6RNSjI3LxB7oz&%&PFkns4qN;'
    b'a&l+isEAr)JotK}`W)OJ8hw1QXL1yI`oQ==&q!}ue^W)X<|5paJaSE8#A<kCRmKbOYYr_q)ThmQP8G8bQpQv_CAd*@acrR5N&2uY'
    b'5|f@<6Rry~Wz5=U$OwV*s1tmJnC*`AUmPxDZfJZ|oAo@b&IHMd_bEFY-%+VW$xT^1V8hzX-J^Y7qBuzX7w;50t90_{^`^{isAMS2'
    b'#OMebMIE~yyF(rkKM(h`i;l)2<d~kudA0FAxE!tqwjg7gbGXvNJ9K4y0JBn@5pBBfrRk|jY5b4mNSm+`zru{+(>=!jTzNVw)bfbc'
    b'&}wY2N%VzhcTCu4he^aQYi=Hdvo>aIHKd0i)JM88J5y$6AxD2pl`<iSiGTJ^D6Kx{MK}~RD;uuiCI{JN+2^1vOz~&W!ROU*YOrk>'
    b'dC|UIc*kd?lYAYD#sk-kN`uZ|gNlnO(g4imN?EmZlqr~x&e>^%@x*UzP+yp17s8$Ef4m=DHtZ8oO3~3hF7dzB{$>?NRwqY?nX)AZ'
    b'qxTt7+4L*o?Iz77G3Ixg|DBnh(q+HMx)_W+BSe?6tG~6z(?HW~tku(6S8%MwaJ9WSx4l$umW*sj_20ntECg35JQ7CN(Q+YnofxmW'
    b'mZOT_Xv#*Uw@Df6T~}~YvH@ew&BKbA4XiV!Z&t_ol$?s{t~E^z^_zvuvB!{BD;rMf??N07`GsM#p@8&VHF?LR{kjXH6tRkryWn@K'
    b'uJ0EEKc}D+_10TojPfH?gR0|lP*Li*4Nd_w|Dn}*U5T1x3a}MHQD=ol8VHHkTX88(5xELI4u{gDZ0@Yo&M~qlHWusw*M;&pj{mTO'
    b'm!643hA5sF$&plJUDqz+Pt)PIkeXq8b~*7I?^yq(u>{(}baXEa&&VS7AUHUL-|TuXXTZZkE^tQEk$3Dth($WN$<(;31#tpg7}^Cf'
    b'Y8N*o1wRN!0GEm&oW<(<U!52pl)3<Z->zys;uh2Z6VgOq<aBJCnQ4nXW^xLaxS2{8w3M8R)Ft{EGPa^B5Pl5s#&4fED?gt&tN)q1'
    b'#LUZi4uadb>PnUxoh}1ax>ap&1(d;lQfWynyu2fQMvlhvqYQ4O^mL4L6p`Ns@wqPhB~=XUYA1ZCCN)H#^&G5Pm9PoH4+0)-#!fce'
    b'n)SS4-%H5#j0avb9(u!c_|4K&ktL_2)rp&!dgSaxxNbP`I)4eg2)Nb%@(ang)c?+MC4>drvr3EiX)7*psBK#5chB`dH4wSgjD=r^'
    b'Ce*Lg*V{Oyf+N<j7}cAZYwBhgLu*l<nVV*^FEg_^4S=^5=kw_{>=sQ~d2Js;xZ$p5gii=E5jKzZcSE|7Bk;3$<0Au;qeE=mo?qBv'
    b'6(rYcb2t8jZj}xN-YE<d2{WGJ`W9i$8$S&JWzZs9L0`)ZQ6~l>HscJHb%9n>ZejRJUalcl^@_7ja_wn2!aQT1om!BDYCUyD`C%*h'
    b'JYAm}jF@L^uumK*k{(r5n7YCfs@M%oFtfJdLyP{ZVDo%e;w!T#PYD&`QZ}Uj{B#~u0Pafp5O=Vn0pez2vG-P7Z}G`!R1VUs!S;IY'
    b'RX5O93l$n@sqSyC>}xDXQh?I-))gTUz~}B7V`rrX+A=dW!Iuzn3K1}*2OHA2Ks+H+(-Y%1`!tGGGI=fh!zF92rkm)(sL#96f2S2Y'
    b'<rh*^+%a+ais<znocrS^UyO&}R>ylo!4S%pUrcjcBg7>R6JuQB;EzC88MBTbE93LZ!M0i?dbm2+2HW6RsDlUL%8V=wd$CazrvH95'
    b'xrgmF@1*}0anU7jS|ukUus!y|!O`7@IvNGja?<~dE!xx&KBwTDQe2xVIt!$Ytm|=clqSKiqfF^W|0UVFm35pcWUuy-(tt9%{!6E>'
    b'xa?*ME*{ARm)(S5OL_bz7;V|vIHU|nRLf3Bm!66$J`rAgY_EwMiidyC3tOd6@;9;+ZyWk}`T67-u0EY2Ku-UIob=!AD#6+KpVNQV'
    b'ADQv^v<WjiGqeQs-Ozt#`DpYs`1<WSHm&v?(m=!hmy8EqH641LpLr=h9*SQPRU(ZwG5z#cr0i%d${*=zpBNsnh|1=o{|$=MywUP!'
    b'QN;M%eEX@qy(_qZ=rsiq>k1;*7e;N6NBb1U_{d{@6>)y@SU*Kv03r}JXOyu^o4y@!#SFJT!FBu}u?NhO>nmo*A?w+Kn7N+VpghBd'
    b'D4BRNMS|xN^}pm~q%MgI($Ec)gAi!d6&$U(d7v)$aP7^5H8=Lx-aLR0c(1v^zaOZ+mR)^4r!M~pQf#~`uVl7y2Nb;q9G@nAC!`pP'
    b't%zJHkJ^A*<raq|R$a})!O@*-bFuFM1d}*8n^jEo7xllH(|>W2-LC(+O1l7R5(NF9jsNYrvy%CdZHBZhT+A78^X(^d-+7wN6ojtG'
    b'3tgGV%>on%^}n_tVhz4QLnvar)d{``?;)Y`n2mgBJ*)p|n+5&P+Rfxq94B<re|$SL#ic5DtN+rOai)Ix$54|-P80B<UVhrXHh^9J'
    b'<k+w}Z3l#l^WeVqiZkNM0e;mD{2=VGC}$VmOHRjF`CecbKvY^`#2S{OGL7;pJC|s-N3eV`kO{&#4a}kMKqa6l9mi_;u@{S&E%T-7'
    b'YpPVm`=g5?aZtytM+9P%jKA>uui-*^WU@GK<)!o)`(h#2@gF$rg78(G0dLnP`IntduvjIzB)=3*?0|gQQl)2UFN^V<^<TU+`x;AI'
    b'UBU5!h}GO^)mB~lwq|Yu*XnL29XnKAKfu%jwUNFVzPLeo&hFPNHiy{|iT-nCDB)M@2`kN{i^lmyMAL!|$850c|3-8r(*Ji?|I@c<'
    b')3z~Re>xf(1+_0a`cBc|w~Pm0Hyn7?u>WO!&I@>lN6=+Iug%z@O56lxD-3%^73ZT%-%)gIZ=?FWI07S$*$`5~Xp6G9v)~Hd^Jr*a'
    b'V_A2VwxhJLy*RI}=w_?&I$kY?tIfL0E&9vNx=S4;1?b(1ScGK3%rPbSm=3+^Vf=q9-x;UI$M~SazI;(!m(DHw<P@pq<{^G8ltp53'
    b'-fa&0ABD(-cT)P)&8p-rs-(@zgiWf%U?n~zvv)R}p14_w_oQGYON}?PUt`u|M_p2YGIFIb9xIuAWP>U_ZJp(+M%B6MtC_{e_MoWR'
    b'%xB@+G-*4LwrJ9Jz(?SPFV(4RP};zSNlxQGtS%jcYCitw2X<Hlh=`F(zWAZD!pQZk%d=7LP1@`ix@(L28cKR<4Ba(`o;p)+eF>TX'
    b'(SCnRHPV6MuBM6MzMh71W#T4yb|@qwQW$_##}E>uNQkak<e41QRb#TJ@WMQxO|o)`UvY%^5U$ynafjnSPLsCHhU<th`HO;cL?R#^'
    b'L*O+WNu@jvk#?|&^Lp*v@CYB_^S%R-KQvaK^RmM%l{hafKP8Xk17P@8zp88dMgPlJ0vpqd*~msY(t=@o2!lH+)Z;9zn~^LTVj1i7'
    b'<Rl{bCYCJ2oB|PApzw%cq(hWKMsq%ijag-HXY;wKA^Bme5q-g0dg_Y@I~s>Nn~=@f=VB~;A<>(dt!8Y|ry;LQ9c*vF=^SQZI7uHL'
    b'>}}FqMAU&!XLP6k(iM9A)E+k@tUxdZvte}@=Yyz*rQVz@bDn*MceSRYdz3LOsmC!D@%~-H;x6aqbE5vMl7iTbRoWKxFLi={v+k;N'
    b'N#3pFe@_4Jc<}(?PRIYn?S-$Iurf8B92@9CG*Vx9LX)zEEr&?iq)FJQN!`{_u67MD5HlBqt<-UegE4z|t0~v)F36c3XquWrAf!v#'
    b'#1Eb;VtxCYtE8bdc1KnVD`gRBI?~lZXgdn#ZdJeV&1hd21eP27Wkbixgg`!iv)G603qn`00rTt~+N8kh++(w0oUnwSt=lw9*6Onr'
    b'bk`2BiL-srnliR1qP_dYp<Q7e(HM$7+}(nX+*@DD4>!3EUCt&-s`F4b6ad{y9=WQ$MDAw%AMrmM|JiOI|IxdQ|8pv#IL%c!BF_**'
    b'<_?I)<k+bDSdRM}Is?IH^C@Y;%ILM+ENZ9pfFr$a%EVwc|I0>_w-|DsN0%IDlOw`{cK$f1B4iD0-Amfeg0K~Ab|xd_4)lLEH06{T'
    b'@`BuipG9S(C5PVT*TlL`@4~?qMy};Tn$3{Y{#Lf02aZ4<#SPu02Enttogn6SFFThcRBuKIOCn}d451#z`n#&H@7HBKtBm(kM6NCf'
    b'U9O1Ts7?tn?0eaC=nVu*#sjahq%S@oKWt_Go+nkYKAP06$WPnL6s*iP=ZO_K1r|ib`xb;PFF74M&{_k-=9b1ig9^ke@14IXleY@@'
    b'4G394S@H331Yn4e<>4y|BiE>tf(`p$LH}h7P>=30?0*%Fl^>4GZf(h_7!*$&|98@Vw|Uk;TP>m;X4pAwFs<ZNG;ch-_z(BAYcrlj'
    b'&QhGSi!JBKcy_3(#nX6>z3X+V69ZThgmy_o1QmkZ6TxJI{3NWRyVis&>Z;a{^>^X|;lw9K2AedORI%PBHWvn8?AxflJUu-%F+4Ci'
    b'Iy^N#dQa{pB>i{M|99BZbn}dvjXARq2rSL)gPFU%cSd;Ln#E;sk4-Rb;pVV{HEG+#HEjHnX(4v1(y_I3u^S;T^6+P1y~QWO>hg~?'
    b'YcI7G<#v?Hp(luV>++8l9}h#H;#MqsD`S03N8TQ6uXmcx<KusJ{}*ReY;j}QN^Qo@dilwox}u?uhSA;*#6M#L-3Y^AT@8xU+H`Jq'
    b'4+;>wK@sO?pAwxF^A_U`e6NgIhs|^;K}gJd>WX2C7RNiGtlUU4gdLF^qC`X5CIp1a_y9q!xky-?E>WiJ$bI{7is-dCsU{^DIy}%?'
    b'jc^W?HaR*pF*-Ch*fZSKf-=|K*so0vVzX}v8|9H}(CO?h(!vcs^s$~&W2m^8reVtkS(BlVm6tP+Iw8z!)?7gTH8nmWssy@~@z5K}'
    b'I9~`FRD$W}fmd-+b$Le`6sH;$r{TM+u4J-dz0|Gw(6NXW*cjcpuJ9zEOgXJ+MHvtcLQE8~-e|-^95c=r&CLxGzF}axw@VQhkRQR8'
    b'm6o20s<@oVjXZ4QCM$1S|7Vx_x78`){EcbBES*USM8+f-m^eS{m?<<O=#5xy;zCoTjYD0nOrP1ZC6s()Z)3UB0#V2L<rxSvn_uPz'
    b'<kbm&EykO67cje^1sw#f)=|M$2&3UD&L@_giNPgvL*=m*7m{jo54Py8bXKTfy3i}J)47g~^fy-`J?yS!b1slR-nL=D@S$kd`hsIP'
    b'6km0-&z<0#V|bva)`Tuod-FiW`GnHbQQTb^5v=AfCO0TgqsPI<5V1&BO1sy8M;E}&8V~pD_rHR^P@KauCgY*E5bv>Bt@=`AzWU?<'
    b'xCYoj(edy}Ze^Os!F+z5d3Ot}0#c)j^DT&21Iz5H&>&VsB9p)OX?VKA@Kx7d{Vg;fIq8*G|5y;Y9wvnF5AlPZ8+BC1`4>iS<c5X)'
    b'^CLG1f<Ws(?^^$raen9*sA1R!^nZ@^|8B!GSXXD2UX!w!Id>MT`)X3RPucHbbh_yVABMY|Ta4GMu4WY-c?;6PZd8d}#|J9>bbvgT'
    b'-37xd6|&%=&PMS@6X`LTv?gv=#(Jyb{b4+nSF#3Ls!L9Uv$!i_Ew`q9HPYCEh;`iZ_^0#tJcVEhPDh{fLiLRUBfTAN*N2P`_0|=h'
    b'(C>RmmB7}2=I>?EohEI&@!%T>tBTmn*IQadcd@>Cd!AxpTVjAd=cT&*V|?#$U2}+XHtR0Ig=y2aG2=%#xAz&is={b*T&X<97njeK'
    b'kOh0{#7(-a=ipWl?n>rUggNwUZ~V0|${X7wJuz}ac6iBSHsT;qU8FOGae<?K9l|8Iy(Ea++lumPZX75(6{XL4UY)Xq4PGS%u~$+s'
    b'gi)XM9O|w5dQOYs`ao-~eVwiIqX5MFzosX~`x+}+jW^)CD=wy#^YeqJqsz}FKnZcN5G7upJIa)b==J=_gDTEv{`&891BE)3#qDgt'
    b'Px@x~*}?V(_bdD*5iI<af?E#628)unLPJ<e6}3(fb5D18ahE(fGN?*nQV9>j#$=L%g~1K0^AhM=$Dfkg6ZdjI=;3f@qQ!QLTY#kx'
    b'K(NkzYV-88^iCO1`tO<w!4k^OCCVe&a#MbApshrqN(^K<a@IC^)LQf-`-G2q?t89L;Uhh5@R&$};p5EQU@TlM0wF{`@O16Pd9bMQ'
    b'!Je6^aW+I*Yk>2DgFw3%<?PU<1eRY&=_pfh1I5=`3|ECXhvNUc(|`D7W!y$KM3Bw`B*VTJ8`T$@wHFbSBd%!CUu`j5<6mf<w&Gm0'
    b'R7V*C^}H7SwMOL`bbrIXm$(7&jp{gWMa+6#_6tq}HSUdeb|K}|<me#U9jPBOYedEH9o+4@R%x%aNFG`xehICEMKPo5Xyosj=a(^z'
    b'_O>I6fVCj4Xf@qvGu>=2&hM<y^fy<J^>>T9>Uz7bXvX*ni32PXyCWZ|IG@DsK;&+5Ej<-kel{LLhdSx5Ho%Wa4(Rc@4OVW|I*QuY'
    b'RMA<kgdlVC9jMjoC}d}uqPM<isIzHopjWu_$mRAlTo<Yc6@@B-$6*0##uhe(!6h9t)06zbl&1<8C&TSa)Y&YFSvphi`6g&SiQ^wu'
    b'A+DsF`wnqov3jYTrEl3gAl*om+DqlP8~-EO*QD)K$FAjXkCjKQ@2u3hioeS;QFdKLM?;bIprX{V>(%i-$X04@9u^~cPXRE0WQ5<$'
    b't46OwfC2N)i&)>=Q0B1SReb!~>|?K7Uo*FO_?u|nj*l@HZzbTDu?Y*<9OJIp8}Nk!%t#(f!avYyhL6c-W@Zp*>5`GC25S?%VZ%0?'
    b'$J^UoZ`iL_oGy%5qmK7h#jHoHu8!Nl^>m*WW3Jl)|M^bn&*?*jnd?doA|+M4Z{FUgT8naN{QsWoKO__>l{zsH(W5FMKpF4L)`YOd'
    b'A*<NvW#|faV=1E3J<C}Ly?1$D=nCOWHaNKwhQUSD&levLtIa*s+fXVU)pvf9n0UXqyQlQHw-B}p&f@eWpE-jf^DS&!eB_;n2d{a0'
    b'c-<{mr?}otY?CC^^BJy`E}HVxJNV-awALU%)o1O-dtYOj^GJwmh1-{gdVWX|CnMZ877vfPb9^|GFdpbe^z6@><a3t%Jx^*A{j>?b'
    b'g`vxZ8$#z7|MOSWpggC|*bT{ofgy)#6^CLxw6b)yC&KueTy~!wJa}#XQN%MAmnj2JYkHXr=xjs?(Os?YsWl=NMfmy;7jTMKT68>&'
    b'O_t@ns7c*gc{#&&i)Xw@A5O(jsTfg#^@S(6!KlO4*K!bF**rWe$#eG<o&hK>(zA$ePJA}0u>Qv^tP8SQ`dg}y4s=y%CrA2id{+{-'
    b'r1d}d#x^E~`VbW(_J%JQ?d`xjTa(}0&hoYH){&l8<OsuE?0u+<<!;En2ixme;N9JV?I*YaM(gYhF&`q@Z1Z}Eg!C?BarN>o9un)p'
    b'q9lQnReTENjB6yupYs++b{||h$5(tLZL!|sfO8hiEP4E<+3K!%u1|^QmI6()`y=eP!_58Ic~6fOefJ)yYrpliq4Z2#<)yT$E9uDJ'
    b'hdY~W^Lu8C(+ueyKH<~q@`TU%?CbJy(SMF^&YP-vX1-6(bQrny^rWnJr;5a6bdE>)5&mARYc_|qN0`)P?`Ca#di3!>YkXo6?<w<~'
    b'7J1IgX2h)Iw)dUA@#;2G!oSZtbe-nDO&8!W%w?H(W!{_CH~*v7|36Cq61x~%GjFxHd0E8&tA*rUSYSUJKvDy}$Ex^udn1gi0?%_0'
    b'%tPKp|KpE4Zw0poL)Azi5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-'
    b'2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YU'
    b'fj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv'
    b'5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@+IyM)zh1=$CS#bP$IcdOZIwb*~OQWX&h1OkCT'
    b'AP@-uOz}S-<d5{U54P10bv6%mHjNMUNq-{zlP7@o4=nlPVBx_3G`9_i+lc#eAI-PFyOsM7*(Z|F8SZ7~zO`^4xIcyb)FLgj^P$8v'
    b')@)`UZdC?{^3R^#Y=3bjaXc^E)_w}Mi*5D@_{z#QoA2e%zgEQqIyKf^o``S{I}vLRW_8Sd`1jiyMVUPaXIs40Sp}nV)5KCE;mm+H'
    b'6=r_iOZ;;#BjLY6dDW@g718U}34zKO@8T1YQvJU(Wq2=Y+g<N)qY0kN?@qp~PRDdTvSfQsoy-=yQdzjqW=_v;UG01kT$D#5dhAQ{'
    b'Y~k^zU|qr(-CZ_;SOdKMIMs>uRt+uP(*CF8?)D?j-H4tn+--3Mk+<)1$D@>z0+^-cpKD`Y^KV%v_KokXn>g00)n<1vQlk-!*eZCO'
    b'TeXqoN(EIhi<ZVIm4!UW--Y{_r-98zEKX8jooi#W*={yg=}&k!&&=pDpEafjo3gg)Qvym)MzUk^2N(9@j9K(1f?nC<9MA4aFyz_L'
    b'&MCe!&kCK{BAT^F8Mj}EV8*<gvq*JVQYw3>HY+b;tm!DfxAd^$*@Ze0`^&A{NIbjM%>ku{n%g$Gw!Ry=o3osJ@L;ot8z>jU+!`+R'
    b'q1XpG<JdsYXn*%;f7eKF`^4~oP;7U*J2?*C0gVmz4Yt*FSL<60*P7Jl8x*JO3s2zHs65lGz0_Wu-&<db{B&w!+<p*?u)E!3<6~!~'
    b'rsl>0>{XY4v|fICW@>T{|2wO(HrwRrP=8BJM}@k@a2=;Z0UFiknlu+tnC=?GP)8%q%O7T}zpJ;QY@nsOzqx9tt63=j%rw3k?rt6G'
    b'Y8mcs8SU$`hX)p$XD2w9@34q1VzpT9>V5kT#WmC+y?vJid}eaIS$CyLcd1!_6_(RkslDYWinDj-wwxRr8ECB;Y_A{cY{Co1HZ?Zv'
    b'5}TPNO>0AMg?&zp42})<q63cgccVYTq^Bn)xQ=X-24+%267=89^k1K{$&eAEOY$$_^#7JpBMHVVu0F*cp3FB=b(o2EiSFiY|5n#f'
    b'jo(2?)a^dfsRnQX(~}dZ`Kj^Isfn@asY$cAyKAK}k7=G58$ng0fd<=ZnHscI4YXFH)gS_pvgwI&%k1v%qia5_n;3!eRChvoU^eOt'
    b'4f2!qg~y?Okf8SBy#D4&UQ5k0Q_!MD^?8_9UBL;Qkw5ZX8m)yZ#@Il2@$vAYBX8qXeB>?Tfmii8FZR@zavPZ4dq%!ixnEHpRpKUH'
    b'#!g-OHf`EgO>(d{bN66Jqr>iwX_O$3HrqgZea+27rbBOH$HItJd3&G94_&E<^H(KqRwc2QGGS9e#M-<)PZx%*)Ff{*<UC(~E}^4b'
    b'Ju^M+Xl(36C8wekkt?)G{@Mf|RZ@^RlIhOagxc$=E5cry)NSg-0A=*rym$Uq5Vo=~YP}-XPafl25V0;FXAfJAB9)$s>T9Yp9Sv1R'
    b'uhS%LQpRjB9C$-CC*#qun{Pj<P1&qY3c?HC$7+?NinmHI#VWGr^0xZIQ-=Mo79HJFdNN#-@m!<!Dqr~NiLuf%@ug>CP!A<1!l5?2'
    b'!QVoirY5_p4GqdO)z|k`UCFGxl#2KIf@2MeQ+<u)<Qncy|5@b^cQxn3MB{zbao)<PRr-A|N#w^i=Lmoxl4zr5-BoS+PIZF6I?=x%'
    b'Y(;M9YSYP>iID-PV4imqT(onr>`aV4>p57vBF?WcYC}QzS{Q9%w6{Fg4}C|Iy0!TDUbHprWT34MQtvvZ!N>oGv>;>VR$X#H>FF5s'
    b'Oax=iy35$H=-6J<k$2ETjfdVSKDrmZp!#Yigs8JZgLqHK`dy4!Dwq?aLj&y%J@qB+B?ZhyYA!UX&vEh9g=X!=R>QTfN=;u=<#10M'
    b'M0i%0U3|*S^i+Ryb&LL5UBU5+3rVG?B8!iQqJtD43q?n$x{?L`?5!)F93AE_4<4{dd%664BFbER^c`rLe%~v)oL7dqu#N9BgB=Z3'
    b'SF=oq-_&L8hJr!IlnH^##NdL+4Gqe(Ha-vHwnQ!UHC5CVo-8{Xr_X*~l@Q43((?SU)%bu{e)yWay({uUpHas7=`wercy;;5`Wnl`'
    b'I(LYf&F1zpB~(|FwoQ{5AP--Wx97>ih&77%098`3GAS5>QxLfh2S=NhpN(r!UBIuJgpCllg3za%G?zqmy_?9N)01(1&dch!^@g-y'
    b'9KSGPH8MecvcEQC=WtKE=p$S+GXCuCB?@`eI#b3L>@JV?LGk!3QkVV0Xn&9E?qWT_&z4_ER>o~am%-^&alVz8)1k(2M(7AaGGakw'
    b'Jv~0$4;P8RUK#JFPYu*1`>W$OnvU*;|CNOQtT5#llC+7w#;onej4k@CXN5Gxo&NJ**5)6VN3GQ*`C)sM+<55Cj&dbD_{4BO0xB-1'
    b'8W`<u?`tT9Q-(7th*+ad4mM_n7&CE=f#`Zt>8{N?Dvw-aV!v)h2`esV@=i(|u3;G~FYm%oq4Nt?!P|N1*#tNvbV);MU}5-*s%tsy'
    b'C+;lcgT0DaA6>GaE;&#Yy}Im7EN`WAG&Ed>;lS%~SSS_hM-jDF86T)l-l9$k$q!#!ekpy9BM|1P|0CV4(CwnE?WW9aXgH{@I7sI@'
    b'=4`Vk&Q`m&v=-$fYEsAfp!aDLHmVZ*(H&rW5;?SruDmw?7=&FF=Yzfj>A+`*QlsK@o9PBLw!O5Vt>|Wp;c9K}!P1kF>g3G@q01E!'
    b'D`D!I^j%HbD`J;)*8hyH=*7C67Y+Mg$=$mg9z>u0V)5~?(o@l8r(;S_M?)vs(ZW_JB3D7RG^rt_XJY#$v8Wh+GeaHfYgC<wK0{ZP'
    b'vEJA#Z}0N_@YV8IUqwOyED#b0amx>7nu%Z4iGjxbFGJWn%9LW}E*7%ARH1{Li}!^ME235xMy}PS?<hL_R>{eT;uGPfLvLs^c0oKL'
    b'!iCX3<!9r28_S{g=tSBiKXh;erHFYD@YLKqI6m0JHyomOMXWE=pOj5ZveI`}U(G@_HYiWS@%7Z2#D0N*Q=jva3SyPugPK$)1(%;o'
    b'Y|&kT=R)K^)Y&-H(SQ$KRa&^Sii;_zrNYps3-&&p7rIiN`O=s~skl^eqWEN_B6=;P%$U9zW`nZzHk4ws>B(_3n?-`|O+kf_Tr{fA'
    b'vbu^|2hG9Dl(k)*;M-nOc*lKK8iB(wi;jn@<GoGUJCXXq(bvh(Dx%jF;m_m%=phm!=f;(Y|3F(kq7Fm)7U(DZ=0JNRc7YRt0&}~+'
    b'g(yX|2M334vlSf+RYk8wXTeLA7}#A~WY3k{$~8MecdbboyAl2c^`K4MSafvntR?gMe?CbQztNC^4!9XsH$K$wUjMnhdh1K&5o`FP'
    b'p|qwWd(39@oYQ3Hl2b971YdUi^bpt;dW5tu<6~QKK5_?rYLF>=2evFe5sCb6p3${ckoP{rf!9=V8;Wvv;yAF+HomRxHG^&i>oR79'
    b'7_+va3>6nsrPB>ASISD&S+0^ttSZXc0prmm`qktfW;rYy8nw<$O_^t=DgM7F`mc=hMZ2Ioz?_PXzGD%l0nM(yUL5<yM?qU+H^A4U'
    b'?;yyjxR^H5(=G|59l8&U3Ib?M-(t#Sxps^3hQ*!TS|xVdS)oS42wkeWoQ7;2BI8#74H+R^&+^rzZAT;~8iv(Ax5o_@nGrL?DZr3W'
    b'0EmVvApp)xG*N!DR#UDjF$fohFi9P|0n**5ItPV>#7&KjK-*@fCJ=cdLW7U%tuLv|KZ+b&9=Tc`y}lsYxBN<ubese!DuPS{x>eRT'
    b'9pbLD2?+9~88tsH1FtdM*@WammAnPHn4a6731*y6qxvG>9R&Bw^@~>HbvOu9&Q4r46V)=MG?f-*r(SUeQL#RC6ON`y3PAQTN0$+O'
    b'bZ3PM?f~T(?QJtpPf0JQ>iRykAS8m7Eq-Go7tDK-KD<wi4kA5a19VJjncu%-{dXELskoG`idk>s0%k>=??7uUzBC;TMU%lJz!J*N'
    b'C0Sh4F+Kww9nz%l)F%fPW$%E?Xx3k2F14!}{vGnm3@OR4_+%7|fvwJC{&04jm)XIDG|?A{0B5K(_9ZmpfQiLE>BQDl*qGPY3zIWs'
    b'Y-KTaV!&W~gLHlbxgKIC<|xxQ>oa$W`tRH|xQ(l??}OvRarkh(t+;?6$+w5-!ZbcVyJRu579Z{FMBc}=H$%vj9Vc{H3HzI?lnFt&'
    b'DELrqQh;IK%Vp={ktrZWMM_wDI;!kc6dVV>;or;8B_QUhyqHpRJ*WD{L4+~5grb~XI0E8xKDc7DwDzlD`kxex_Cm3-O$AqVbL&5n'
    b'8U+9BN?|<lK5$YL@V^`SuZm}q2=jpGLH|9C|JV)2)>UIN9(+R?gMa~Dd$Tq*r0QzcXkUleLmd(ai!j5591|S}O{tFesk(8HPZ*~s'
    b'C!smhQ&Z?}&~t#z;mvSIaG8O!I+jEd|HH7iXi~O}^ma&R_qb&zGs1#5`!4WVEXL#d8gfZK8Rw&*?iwREjIbFJr%m*)yqZ1tESPZ2'
    b'>8Y`S-s#B+htU$d0V9QBVxGMNC#}ADXpVVF{!0Y#aHgD4Y=awWF<j$%_mt3;_-L&tPZ7h%)mt@*{$162y8<w^;k_!FLlNV{CG~=!'
    b'S-A>FWD5aAbT=_FI6geUCO`*!#|F9~5vaYf{%*K7HXXzMY)7JD;ampaSjb$EXX(?~m<c}fK{8h`QTk@*wNYmL+N8bA3pJu;h}E6x'
    b'zjW%EjoTNVQbr4D1(FfLMOv+J(8v>6I>6kMZ*Ad8zGWQ}2dfnUJW?lwsc;r$=Mwo#;7znJVlCGZwju^Dzm#qt{g`dgwxV24k+vb^'
    b'&?frT<{cGk-rc~s5Jzzp2+4)$!E2z&(A@^wYTfI9#ujbbHdMY)vGyvpkHiT2kMbKiSE5Pq>#We&eUQ~n0k{|1PM5JuI#TMqkc_K='
    b'@xfkQ_KRpQ^izFW5bUrZ%G<E-C4^N7a@br$N(g!x!gzIZuquhYU<L)@Ymi;SBoL6OV%HlEyw1;GIIRic^gl?{f22H~rfD4Ye?99y'
    b'obj|3=ZQXrR*>Fv{b$C>g&(D-qRLK3Bk&e{{n@yR^N9$;D=(*2U(11mV9KBDU!1d3lN6{(+0j<2nwG3saB3aCDH{~0)p0CnK`4lq'
    b'CN)G6=dXwlRIq{TP0GYgiiALXP$g}Kjj7YNYtwgWGoMBH&1UzGzEgZ`Z_&{`W#<yilIb()_&+=sVtb2~@9!3;rIo^}W3DIG7o1SX'
    b'ZQ#>qrbwl7Q2}ttY#5g7-3Zd^m1jFElu+PS(~UOM&DNq^_HMcf5kLgqqQBaVm+nfdkqut4FHJX^w3mA7ilx4?Cif6>VMWwhHoX$F'
    b'4qd7ITzq}O@n-GC7TskWu)R1R`{FFky2~A9^2#fjY?PP{m@xgfPm`HlREUdydHt`_Ijr2{`%alc8OtdZi@igjDvG!O)VVStP!S&>'
    b'kMm;_g|WW!n2m)|-faFQa$SD->in=(idY}ygNhh$Roq5wz-tjd7^_Lc(Sl(osB<(8a&V_{Lf6_x%%;3M{hyt*<;1_WD36WXv*>p_'
    b')TaDmnmC)!CbPO*ag9ui5F01>x0T2RA+k$N)%E>o1&BXW<NdFR<8}PO8<b~|%5iB$2okHBydz@83Z12=wJ>s>$v%*7I`roB?1-Oz'
    b'X+1Yc&iftVE|uO6NF^G=l(j>b<fqGiK^(CW^&gTBr_YVg_}9x%d5Hg68IYY7hOfjWFh7;(Tg62wl9)%5s@rGq`&(*M@&3GPgZ`IE'
    b'^j|vj#e4aZ)3NqS*a~xPFINk50T%mA09(su<}aaMd0rXk$M+@}dHIDDKF5@bzpMVkN0*+7W51fs7IAH-b+*#@{>W^2R{w?gpY;D-'
    b'(|;xun&cqP%ZDH~hS4%#&pCR0U=w@^o79P$ASSA$AYLUP7Z3_v+BW0C*I|lX)rJ}Spn*gDUxDCi6^xdx)kzLC9DK7?f3?2wSZ(gX'
    b'nj8CB3VAiF>PmX$rBoz_=nil?NG(gx#44gU=u-prsX^KVZ(a8DR`>D$Rzqr#@!)IxsqF#37>nBHGdRnvD>%-3A{JoBdAAsEi27fA'
    b'JY1KIB%KX~8Pc{CMy=1?vz%Mnu_ABpO1$TXuFTuZzdw_^cRBlY&(lmZBUdA8!qMbmPnVpG5+zPp88tH4S+1(hJB&*+9ekBlV`7jz'
    b'mYemC_9=h@M{i_09PPtC@S_kJT%ah?f1#6dmjE9m)&I^)9T$bpSj@BQJO^59<dJKOvbRH0SnXx(hO2_pX;NQk)?UI3-lqlM=&!UG'
    b'uC{VMuB%c7b%i4~W^Q4lxG4d~{jXRg$)I8Xt8C6O3&-57N!i@bjk*ZyTlqSd>K?ZXT9ECMx%JNUe|Du4r#9Vn#V|QeL$)DcW<%dI'
    b'Gm_f@*fu@2CP*}E-*lD|_BB`YAv!;}r-1Ls+K#+cow9Xophr5$ZxN<qlaXB5U4UPseZpFF0gdYO1>vi-Y!op>pSBq>$zVs5nR7AH'
    b'Su(!LkQH{<7O@$8WXfs5s+e`E<Sjz*Z%>-|`CnbKpDBAgUJ%Lru$2hCx@!z@9Bgsd#Q5a+7(e*Q*DBJM!tfQsxMEsJz2eNo*oak9'
    b'0_m`4Z$qg%bt{+iy3v1|;|&V@HP+=HV~H@AR;v>Nki<y``uMBE##Pt$@%oIoQ69CvL3v(W1u9LPg~7m~K8OY^hvkoK&|ph<jmgQ)'
    b'IR%ZK4)MPaKhh=k1=9a_W&G#JJ7_(jD+?W(4al&!nQ25j%o<0A#s<0(YxOl%wCJxOM^MCiqnm4!{Lp3K2<*xr2{53pC!^#ME70^z'
    b'4Gz50*Hq<cp{b}Ib@J1iqyXkM(t`^l*LHBJu5>U*o3V=<gJL;_Hf2+@;rd+1<oY9`FI`F?n~}^6QN(V<RfzhJkiH;vIW&`-Z}P9Y'
    b'd3b7K40b!#-#OabKGM^MclPRO8^L>j=lD?1^yFma)%}PSi}pQ>aw?+N!vhMc!Y{d;o}3yVLCsB$4iEQsj13A)`&eyGj^p@K<D+cy'
    b'bXu6tYSdmvfQka(Xv*j{yn7M_QyBk8{LgEY5dZ64#{aFHs-zT#J%b8o&OQ5C1afn)ibvyCUCY*`1hEO4cpn7PeNC0pCF^|+Wk?ec'
    b'Ih)w%*%s5`H=(Yxp{#ZGb{||Fn{7D}A&*$ayfd5hxkLRIg?+H2Q5hcq73E`ZP5Lfjj#4s9%ex8al{|vYQ@}QKS<mxBeErQ;Xl_o^'
    b'SiAQ%S2~S9hzpzyhu+k%0rqW1E)5it2w_WM7NF?pUK9rEq=;OFd_<eE6X_=lS}vtkT~23998X3V54?(P^7lT?!h?7}#45FUM<zxF'
    b'rDf(1XgKh?JnR|Nk39UDqGMt3!iWtJT0m6c4&Z842?4sCmo2ld%F?XA##Rm>O^an^P$h0cri?tj=Ei~A+(URr8B9msRwf1`O3`NS'
    b'MrLi~W?@|Q-)R}AeSMT1W#A`|RPnymHxF4jljeKM)c9D@@i0D<!U2`>{&urByWTs%e;DiU#<g%0TP(jusDt>b;$li?g?g~Pex$n%'
    b'ndWd;%M>@L$d9I?=B4`2&(^UZN22<q{`Y+RUviJO#m3*oVMCQ$Yz|A&9i(QUwN8~7#Lr0~gw|)j01I(g0>o)Tz2dYgc{96XH)fq8'
    b'dY$pWD~O6aN)`Q06$px827_&N{mqpf<;uFeBf6~J%BVF6^PqL=)NLK*Dx1swU;3=w#*EEIHo(4J9q(5VwyNZ0WLK4Lw66oY%H|X}'
    b'z?@)yot0YCp*JA@P=2_o!iY79<s1SVZi<s%uZWPwn6;}>bq;x})y1BLrGR6jO_~e3G<2)YP(^vvS|k@vjt};%NZt-pS0@Il;(YYk'
    b'&qJ;u0xWQ~hjZ9+hD{>$KpqWQyV)3fN+7Nsu8Qvt_Q}}^RMA*}7tVr1@dBky4s1}JAL?l6Yb@_;EbDD3!PSZ?(Wt(FY>rhpR3d7%'
    b'E@LOMDwMgsq@b%>*IljeC{x1gp%sdb?S+`g!<HlIP$mSFo{qIo<y)lIg0#YT=uI|86vH>-dVSV&sB@?dqz~_qK?DGb_)WQcp3$c7'
    b'G#w8|NMK^||JK{pf9X<xHhPe{9o1rBtJIK(1`Iha)EDRag>jy%*@~z&Y@8>_ujEwp)WifF0b4DTwH+yds3gv-cI^|yIM?hXQBqKM'
    b'ZLydISnQsCY_JE~)gV8KDlIt?h9Do;%ZAF+cR-m9`(7?N5e`Ad2JNMCIIkITS%PG4i$8BinY=-Hw#9fI?bTDy&NVSI&{3wSy?LPg'
    b'Y<$_-*pgEbXd~$e8)yI1=qyc|i<Ott;cj4B{1Cl5Wt%pAm*K!`rKh4A<R=DNtKr#MrkpB_|GVnH+j$nWHQa|Lfz1e`?aIz4^Rf(~'
    b')@D7A2%$J<mpa~CoAK;$cZ=(Qzw0{l+`TK5vEItq4f&zZv=$elYz2{P^Y<<<2wj1c3g&m?jX%M6<Gi_{tC1!bMtSSFyL*sl>C@Tx'
    b'11^oL-e*;*JB8)YcX2NX>A&0cKXa`A_mrLwcef$e#zD}(3~52|1wx$T_^<*lav1HbRI_=6BX4U`LLiL!VXN{Z*5W-cbR}MFIeO?y'
    b'D7iX02oV$_1Zb47^2cJ4-V_FFl*a|IRl%{|1))zDpNwub-PELR&ktW+5V1}X7obeAPb(w_A(YDB^OPcTC6to|OUFX(1N9ckVr(wT'
    b'ZK^0e9m7UxqSqCMKFy-L%w5Ik%NJ7k;EL;Rk??Vak?RWfJjvE4Cj~=f`Wh<)Z{p|zMtfT;E+n%-vv@ycG&6X4%tjPRnHZ#I9d;`#'
    b'XMA8m`0BiO{-%sxkK!5jztW&QgTz6a4!0HMU3umAsGt1Mm14g@s})9j<4as}LB!hJur<h2q-i*+uB%#)lH(F|8N2xP|MtcI>+;!c'
    b'7i$sft5dfYAKQcYA6d3AFk){q$LB3DpzA@burX3Uv=I&q-D9~}&WlAy_rMD@sm{Tt^Go=oQ+V^&f2oq7q4oP;)h7BGGq<y>EykNq'
    b'd7Nesou1)<CRWF7U~6?UwraCpLSDnARO@Q^Nn4BA>Ml&>k2%!YD3A5!R|1&eWHWa0_l4P?OyYb8v=|t<36h*|tiHwLHRir&(EaU@'
    b'HvWkVHg5jQe$Sv)G77|vl<HH13>n+BN&fu$PwSlbM+-B;Lw#&Da?HBoeY;TqW#<wG+8d$3i1E0}Tw8QJd`egbaEme{Ea|G!!ee%p'
    b'D_M`880Fm@zHHWBs>?fEb3F$=3z5v^$N=K57TslZ0Txw4Rahz)gb)P|vFb`j)#WsFsPVyG8vnT$`riUwDq@2Ph$lCj4!+i1ZS1Wt'
    b'>a8z9JlT(^vbn0ir5a9|57E&;c;N$LkIo7W!jJNE@#>^a`ec7yl0Q1TG9i$kRCO3IbTnH2J9dxEP~S*TD_e!$RDra*ub~tt;%-G}'
    b'0lW|>dAR=<CfZY5gfhUW+KUVL1xVNoAG)h_E&40<1;?tdWpf6TUUOp~j0z5-r@mx-xZnPq1&hngzxLaiM~4xKakrACm!66=?0XRs'
    b'hu}(;9D*oIm-Srn@zBaksZHwh-8IHpXXoxIJ)(%=GCRxFt;QRO39GMV!P=|XD-EAfR1_GgP+wCe<X7^DgW2LujSltJ6%Vvj!9#Ju'
    b'@TQ{d?b@V(M)k$<fo^CrUvJWZpxFu+?t8UNO^%Nb^<pzr`$%uwXn*I#aR1EYq{Owlxj$N*&UTVMQR}QW=lhiT%{oev!g~wzzX`sA'
    b'Vccf?UwkY~9lOrR-K&MDzEN}0DSCI2FD}xU7}aF#R>iP8Db#W6bxD4T$W^6h;;f#ZawByCUDXD7WaLdMgsf4k5oru{Hc0~pi{yDn'
    b'_PTO@M2GNvB<a&goE(<@jN${hxF)mT32qjiIwCv|#OC~D5AGD)ypPir*&oZo&z2(f&}Qs3q;4{1hCsSYPesqMu+3>k7+FTy*@VJ~'
    b'RXSFU8ww&;YvMN`P(-#{edB;Qw>JOLc&9;rPcDPEpJv?^gl)*j@$NJhO1L-r-_wfd5m7Ohnt3Z?*qu!UVJnc7<%b~-Ux{clKa725'
    b'6QIImDBigbd!EkU`!sArofxRg++A`aqFH+x>gp7~IU23SYBx*Uyq*`tEZ?>7cnVtP`|L!Q=jS*+S<CD=fhD|I>;iB9&;9cs+%3a1'
    b'OP{4P&$W(1ZtEm*!XgkI;&yccyV({F$mVh@y_*X6^iUV6=JP7#t~)#40LVYiXhwXJl4OM?r&{=l8}4W?DUh?7%1!!|K*(>aDR=(y'
    b'KVRT_<@v%GUwzICh+yG=YjO`eEQs<H!CC~{E<PDmb~dj3Tw>Xo*vc!J_WQy-?<;vg1S+{+ak@!&i5r<Y-|zD93b&6T_4FXVcc%-x'
    b'FMzlxOZ1`I>=%{s{zz2i(Hlxm#n|S2#*5Pv_VB4ua{*oh)mVN$kssx2E6VpY;6H~+b6r_@#_6mN<-MLD3;YACW_XK*6}1)TH|wu9'
    b'sxKg1u`i1?&!?vo<`rL=X9ikp`O#y<#yzzr_Np-;gzl=;bXBNWzE&#lC@o~G982=ri}TvJm5}Yl`S_`~zId>sVYI&sIi@u9na49E'
    b'h4s<gnlk&kHS_GVDCanigLg1nB$i{7JZ#Ow6WivSgA0}^7^gkSc7E!eXTfx*!>*6&bzeNU&%3ifOH-&HZhe09NOvnTYy0Di&GUW!'
    b'r|_s%@qw!zA4Ym>KjkPpPV2s4R9b!!?~!*52Vd{w28HH$>Wixc;p*6pA=A_5>FF7Mwa<K?@M&?q|JQ1@+{S|n|M3-Ob{=YcWNff^'
    b'oV&9_d@$E7_mmDKx~47GJ9@U;{H19=ZB6*Q@FNZZ<Udc7d3w_F|1WV62N`auWB;t-%6zO#8omk-y|<X>^B81z(S<kyGjmTKUi}Yi'
    b'|I&vr^H1e9zpEDLl#l=4tpE3{ac6H`nSGGEW%mCi;VE9V%!Z?GpMgwxmtE4k-VN_T2q)Z#aVMk1HV^;Dgn165+5XQj6nAr9-fbp&'
    b'|HR1=fk1fAQYR7(0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-'
    b'2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YU'
    b'fj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv'
    b'5C{YUfj}S-2m}IwKp+qZ1OkCTAP@)y0)apv5C{YUfj}S-2zLpq)yltHIEa5z%@7C#!v85RK>AN05dPs}SF6QrHJh#c2m7BwKx?&;'
    b'rg^SIp>9~6QT$IJ5dN`3R*TtY4_-ZNV6l;`d8$TKj?GptKV{heis8U({Vi4em*Q~H|7-8Nn&ZgQ>@X|MDnd_^LLo&c^sp}*Aw}p1'
    b'NY5)h=xJt0(c9DXg!hiV*_Jb8Hwo{{00l#kp!XyQ8W2^5@*duM@4YDpotrl^E2~fd0S>!&HsT&uR~NIgGH>2{zw@2%yM`f7A;{<M'
    b'{cYH<=#kwBn|j*yE1&QR@2A4v`cRF&I~De6*t^E0nj}nz44jG6AZA#n{q<#}e@_(@HdDG!14%n1Ysz1!;b@hvFV9bPS%!?yd*0V}'
    b'yp(m;EBiI~$DAJ)#`?S-PlzRcTE~#~im-$h(j~;cB%ZT>f?YW7JFM;VXX4Uc4_>&!p4aD&kwQps!FkWNr$y$HC{t<NRJWC!<8jmL'
    b'h{Q#>YZt?dU+=D&y*}($$)rfWP{Ks<!upqRMGD*~xKzJRXXO9vP*=5QJp>+&al&5{hXmX2K5E44^LsgS^X|5_AZ8%xh>vF^_|6Q='
    b'-KAp#SL4WoyP$_=IV7w?4Z+8=hr}-EwGQj@#4GRjXyJ6uzIX9+f4E2RlBy7r4PhA7C)QFJtLLiS7pQj6_GVW@rLinYn|(x^d&*RP'
    b'&RX-0wd!kqX_6-EE0ZkAdGGqt#9%1Tczq%P2C=Tsx0eK!bPt*>38p52ylLhCCFCPIf?tOp=p%Q$lw0Kq7J14{uR}bD8~b+nC!+@?'
    b'MG{j++|x^40C!oBd)vLW>2<rsM?eqXTwU5&S;YJ1>f*-A!sgQ4#_~M=>fYWCLzq6^0ijN}Hr6(l=GPZzHdhwiTU$Qf^@J2@hi@Lq'
    b'hfk^b9skza%I50w_QslfYXeW=+1|qA;8{E#kC*G5#9j#t?1<Lv^Y3|6fnK~5t<9tMcgxeGK3ctdggjeoOVhoMnO^7i`U-Opzg`-F'
    b'TCXJX3rhuIRgkDU_-6I__SJX?O0@1H75u?B3hOfVxjrwDcJ;u$<Vx@zdD7eeE}@LQk2C#Ls-(|8>iD27jI&i;>{s9OdOgxojk(mu'
    b'(gd3#(OPvGw)|O4DTJKC2JX!bjwm+q96b4OzS!e-gW0y$mcbs>{5RK@H<lORu=c63wYiDO4&zj}O|<=wmYJTgG~PF2dpB%tSe_c%'
    b'>-zNIc#F1AeZRM{Zh2~$(lW>YGOIk^qDTSrERJ?}yePBZ{<F3EGF~kYZgjt`L6NxN!Y^`^^M1DL{tf5dYvZlWBAd}~!RqG9ug%KL'
    b'j`|Aj7DU*LSl<}RQtUOC4YIW6qB#Cl7>jqKJiYaC-ms-%YkgHTMqFsNzqRYN%2sn(Uy^_`wFS}5Me*?Lj$1$WsqcwyUD|(8Z!M4V'
    b'S{`I~yi(Hp9yb32FJn}mwbhXF8_JT6vQ%SPszH{5myy1gr5F|I=JGQZ)p<+hB~+2^=C}6R9~`%@IP0!D@BM7Mb!B0si|?Y`vyd8Y'
    b'sBXOWg*N*uQ(0o`quj|3^KPD@3J`ItHs`p$D0aHrCiZiNUy%H{8b*`ZZhqhTFxz?OYM=VSj$p`=HX?uRZ+_JFw6OD~y#0lIV`)y%'
    b'JW}Q)@?>Rtblj!xYpQE|Qs8=!)&8uwzv(WHEKLrFcz@5<2AFEh(Kt8Ix;tM)%jVwRTAUbwHk)YGPPXgkhuYT{XZ@V<E>8|EjSp-t'
    b'&(p5EIy=5PH@UsJzT@BdXsQ7pywEgmH{PkSh#oK?@^*O#kRFjk9<MK0^6lea@PC*#%C<Z?h}Y`eI3$)&@REK?ot*SqnH^sk>jO3I'
    b'*8g7jHV6Smu`t>bs3<tcot@>`iP?eHi5B&+>E)2|#bk$JV{w+GHJ%h&6^Uk9(rmwrmJMt?pnKZ)p>ELdTrA$wM1T7WS=+PX@m8(W'
    b';^+tb7A@HFFlVAoFB<9MSZ`;&(th(hLus<UBuQ722-3jqX8WA@cF6b=F^ENV4t!-)UB;2AF0(<FYF1`|d&3$vJu=hhRA(JC7DxAK'
    b'9t3pwz6?go)Be0vmvgi^_gKI7k$5mH|J!Q5GnGW?^G}SoXgG3qQ~tM<#o4RQ8<giXd6CXL*ScO;^fun=daX2<pT)_hvV^v0CD6n4'
    b'YVcF~!f1PWim^D#SQ<ZMdgbSHP~^U7XhU(FRUX&+xIiq-fbNN@IMSv}YI{~X(``jJp6)VFbsEuXa5u)17*lDi<IXj74BBD3-c%Wi'
    b'qH$|W<;5YxvnlTU$u{kP?h)!%bK^@**3piJsvU{VP!rG>$Jyj@X5|^`c@M+?K3aHVX&kx@BFBN|hp2?!_cwdq)%3or?s;3;-B8h0'
    b'uk5N<biR_I*c~rQ+MgG<Ju7N`k`GI7eU#VwFvouTPv{<^iBbLL-dIJ?A2PkPR)1|MIAto0?|xV7_XW!>uA;yas0~Yb8jZ!cgoDo?'
    b'E-q&HEXg0rKt%A!;`9ZP=F(V`EM;M|S1>@T=}6z0AMVr@oHm!BTb?u(N1+9!MoJq6st-(Jk|k-gj~bv=?p$kml<T;2)hJI>XC1-u'
    b'mWR2EV|`+CL$GObjvI?kqucm{OU3J0XA?TSu_R8DeN>Zss<|*mn;(S_V4FVe<L10bUH+-g*OfSP(D+K7eZo?n;d+>ZFj-7$g^W(o'
    b'K8bHvX2vYl-&m_I7?kJNIl^ptTwuTTgY!W)1m14Njz{ZisD#upDKj9A^kwO&klk!1^{R;UVfavqkZ_uulWM%O$vbMsb^m9OFjTR4'
    b'vU_t~FH18NMVZRa5f>(LRkWh;;HHuo$K9XAqy&U_S3?yZxjFZ^I_szbQca$wD@ju4oa%Tfcig*SRV10^$<sYHTDJ9t>E?ncOKCJD'
    b'9K0C42%_@loFiz0t_GEqJZUWrTVCt)kApM&wGZj>xxqGFVT`3L)~rbD{ZKdVY#etq4(gwPHbI{Dx}UhXBLTt{?qG3@cq{mKL*Z#0'
    b'?0H`sp8tjBhI~aow5l$^j~^ripr!3<r~qYImC0b3{jcx3`;)yQ)htV#Y&Qh)zbxLN%7Cne3l7SQ`u(7BR3rFVtbw)pDWfdep-MNY'
    b'zBVb+4MmZ?O?SOQMs#g{65n!EUnG_gZ4Jw^$P*EyhzEJk?(slHJF7DE1*hl$1Y!YQ{z>?kwx>nDaG5}e<Ppp3nO=K{IN4a5HObQ)'
    b'6=}BW%cOljf&b?wOtNHiSsdaiNjXV|$H#ZNgJzZj`6!8+f=RZ&QlPfs0uYM@>kXd&VFG3aI;~w8i;+g$KF0r_Rs7SK3w0iCD^G2C'
    b'QcS{LS$x~`QonRKiF4Ji2iX=`oW1sY%grn3oMvVE0%dX`Apjq3ue)k0iH3dkYaYR42lyQ7uGe9dr&<*WCPl{L_y8@&%G3y)0!#_Y'
    b'!S4^{PjrUnyc2e1vbE~sRJR4)8&ZFLermSgX}@(vlXJpZb=E3R>{s8TS8IJzXfBPh$dh{B-`<No__)LEw$=V%l_!9gC~0`zZga&s'
    b'n>^m6OkZD^2}$Enk!i?3f!iUz9yUJjc~`qSGb$QRFx8MFi{pJJ<rz~^B-9{ya(=LFWqJhK9<12;x<X$V2`jVJe7iC;PJg()zG|sB'
    b'>r|!MYl1R10{;&iOB3y?RD{o>H9@x<3QvJmP&T+Qj)L%LTL_WNstfSuu9|ab3z7d37nl@j4pkb+S>%6CamCuoQ+gY3@3zNL`+HMK'
    b'tW}XbsDDO}LkWXyQOVHx^fa-aQ6VNprd^eeitTtI6A5<Q)nqJ=0Y8V_B21-?_85wAyQJ>-w+<2l&_Z^;E=OgWWeEs>_UC^%DXTKY'
    b'RGI(<F6DnTtGO(G$Xrj8LUce1<iq*9c71V-qcR=ZfR3kw|3Q*AMPlbG`SSFbQIUaG=y;{v-dN`)bXn3a{(lDF4HHAt&mxj-*U^0V'
    b'h^4;eaXx|wxM?^VnjdrC{n@5WM#Bx6U&CcDjrWqsacT&C0FgEBjxb?seGTtoK25^^sg8<NTlLp}A^*egb4Ed~kBCxVnry4SWRRuk'
    b'OOqgei2f-_M3iBzyy&>|vuA6QA6gQ}fCNGqwY_!S`w1cEbhmYViNxt!>nrfHFf@3#Aic+P5xPpWMJbHM;HcZZJUue%crSz%e#ZZw'
    b'apV_NW3D(4PB4@vY%I+WXdfDjBF)OQ*?~4`njP*KA{-h9Y`HMfjX=O&p4$4PNbnEbIo(#!nxitqQFoP32n$1&ycHN<5UNooL7mcK'
    b'pi3J{;z2&H2U#Nj3%s{ut^NiDgH)L6vV^b!xXy9=icOhfmc{pJ?$P6r&1Tg_VmtEWv6g1s*0a4Wj$3)@xD{8j&etk)X&iJ2%$Ak}'
    b'=O8$RU$d&t(QqJSa1G{<!WhdEmnMhy$xMo(&Qf(56k(DlQ&A_Th=n<aPfc8)O|5`yh*e@2<#2Xihvk1mNdlg?MR1fbRYP&Svntb~'
    b'I?u-uk^*n8ESf9MqAf!B-zZCg0Jc(o;Q5~;XGKzv5YS1r0XPc8g>MJ-Pw7QQY;QDKN6?6^53}ZnI=Cc1D%tJfhC4^BZ;6&rB*7)o'
    b'w3T=Z+rIoS9*2J+PQ2nQxK64r_S65b%h8nZgCFPryVr<xDN6{_|1Zkmu+V3wI?ZC>BaOV!MZy2ps!Oz8sKU3GCqoHP)<s+E^Nu6b'
    b'-P%|KW22LV@c$6_zc|`iea=vl*jyObTokV>PS6%aYqF0u{`5stZgj8qiI>mV?;yrRUD+$o=!#;SZX8o*A8*P!rp7Dh1cFBdlKSEV'
    b'1bz5+#QKIhEc(cwk^lKCa~^Qa@xf4V%37WdpWgfaW_N?C>vcu<n@VU5t1Q-9d0~5VL!1F1PFUqqivz~;iy#(l_7P3iA5Dr>RP}VP'
    b'69UqRDy_Tf^>{^!p!XVgHt7l?jk477Hp9Y57h+Oezd8Su=Ej%myr`M}7B(pGdBuO9`aT36Y^URug6l$aMp+t&3u=TW!ubSI-Jflo'
    b'bf?^Czm30=+`?3sRqQ9j=6a$Pg-eM;W<DV`x;WNnD2apGx7U70>4KBB31Fm_huOZ}!K^F=CtE7ctS`<`!{mhmcRMIjN=<#7{-<Mk'
    b'%M*jTqBvNqr92Y`i;iR{OCc{=3JMQFZmanQu>(pD3q=Uv+1?TzN`U`G{Vx$4cDS4JWWxX4(3=>UhE9|fa%BdHMm*`QA4w<oi+<2Y'
    b'%SqU~G!gua?!CFXMD@S9{H(nq1;IPiokSY>0u@!B0{u@bYNp3#C?>kS?MZ>3&y@0G>$HB_L2HB+lY{iXJjD@?|3Nr3IpY&j6SRAb'
    b'*xpL{pL&O3^D9f`MSW4UI{O%S4B}8%l86_fwW2tCWhU4dcMsA3`|!Us1i+K(OA_E2I~yvc<50ge|662<H0j~v#)JGmkB?LP^TS=J'
    b'XS5W04(+sr|2c&ZUrcol{DR}oPrBTrE%$FscH0nS;eyn&`y~1w5lX-I5wyY929fUW&2>0^R6CAaD>B3g3sq+>i$$E$-FRnXc^<lV'
    b'VYn0V<J>^Y+<*(}%To1?voakzd8*4S7MSMuDE~u3xJ6CA_mtY;DZ5-!baq_O{|%!1CUXgjB5hR{MO`FRyUJV=Wxx3?<$s^g7j_y3'
    b'1V73Q-H6IZER0~sRDQO-zA_}$M&D5<L)LfJTUSlWOmr}u@4WpZ+IQ6Yh7%i0EdTR4$X^K9XTd^A&dLnPLfRZ;kXQT2SR7?hq|zaH'
    b'V4_tA-Hu+-C!|1U`&_!hXy{=$amYVvabu1~V^I`gq-VuK94(L@4W$R#cvh_afvO#<|H*akT%{RQIv0^DSemS`5J4{RKPN7{oY{`r'
    b's5DLH^}pa{##=NH46d4Upb^M>D3&gwSjrLRL$ugxuNaD=oYiLx!Xwkd6aKII8uSb0i4dFi=fIHD&JMy2GUO-d|GnlgQ_~<Lp2aZ;'
    b'ktjvbHM-)$B7UL;=iP|A;YQL)TnxodjQ7&!>M{+V#oE}-|FeA#+`?8aWQ6G4S3b`1aJlqc&POL5fd8XG&Rrbe3a#exdbYVreoNwU'
    b'MG^uQX><S*Tb>!8A8H?Wei*U79<?-#Sn4O+v>o;3rZU7SN$q?eI0XMo@;NF~Ni;n8;#j}n0>VfApNIeX{C~Q$?oYJl1DQ{-@k=?n'
    b'GzhSVOG)whe|aiIOY7r2zc9>%3PI$e&pU=_nk3=NQ)mtF`rr5*x3DUcd0yoJ!$HK_+jIvpthpr8b^ivR6rCB>6~$Z1Vx4tY_>nlt'
    b'h#0IAQXIr<yZM8-zC(~qbL7^lG%LyPx&Jc#-yrI`ai0G#@OFV7!u1VA0RsQ8)9xA=sFh4D=F)oIo%Q8pP+NJv@%mQ?oh<SM)OKIf'
    b'oqo-O0o~&P-4h6mLEU5MKrj#LR+D>DSC-yhuj<!7UllwBWAD!^{-HE1vII1DPh*{U5SoPOWO;(?K{lDR?(tY_zO%^_EvgIr6gAGi'
    b'Tn}>4h-O*Ru;mR;FH3W};&=xXY}G}Y;itj7DD665SAYcITzWs$iTNLWG30utS(yf*6^QrgY>k`W5o=YXOi3n#iC5#MZ6}iazlNVx'
    b';uogdb-%4K6h_)q83X#~AyXEe_p@NmhN2jnQxa*M<Nr(C?NaAQy2acV@4tNh0RL0{&qX)kG!-e^%JeAwBfJc*xv{dymw|@H!dw?4'
    b'35C*ZH@_D&<f^Isj2-??kvh}olBA4$fkc@yndE<HZ7<L3N&Y7T{&9I`Oj6r)-cAdO>a0F%3d#RdeHg<3aEMiBtg7>i69XY}2iIgN'
    b'VB=vfH_msPm&%s=*Wq^-$NNI=i<X6SHx!<tqoo3Ye4PKKJO-XIlqI8O+h52J#s7nb=R6S!k01n~UOHFGc_$42bL+n%t;$qwK@4IU'
    b'sD)wEOT;++ntQgJ-|7oa8VXN4?_Q_LA4-zV`KQgrry+j){8+h<j*)f0yV;z3+)@^A$UpAn_?-G;u$<<`7pBr!#7DZ)Bz;Meo|`(Q'
    b'&N-pYIYvg4@BX|(hm*L<S(+R~#H}kht;s%yP|Nioi@fe<K^3d7e+gmidYH4Zvf$a;bUn)BzRhlZl!rp<3!|*^cyKuQ7FK}ZqW66*'
    b'e7A4kS=l}^tBs4tr^gW5fDneLpW>Qt)Y$}UvV#AGxL9!0JpUus*a^2@hHD@4_(P^w+N^&9)mT*L9k+h4)m*mU{Kiswo{0S71XF1Y'
    b'?x-t@)t4rbyDKxyigYe=PqHYJ5mkwOiOv7{jB`H8z*bR=vnms`gT5qf*<n*XI04cT=MX7dL{>)*Ti*(V>7$bX^@TBr9SFrOFVO2x'
    b'b(qk@$)IF;CR%NVOsMXG_n+!C!OGB!$UKl+SGGAnLi*d}5NNRF=6Ox-DP2i2WYXL~>ukSkb(Rnsex=DdVN)bJZvQwt(B|IUpwlnm'
    b'XduQkImew<XJPmv|L;haz}s(MwaDU3vZQft;-c5R#Sxbroefb#pXMP?6p{f2YxQM#B2#HRV)@OLB?%*u6YRG*{x41VX#StpPx}j*'
    b'F7G&e4a@{Cz%L|}z!bQGz4klUX>;DG$qobk;nv!UrQ!?;TZ-d!B}rqB_aK3#iGErYs3=ouf`g3z=7`hm`?U|WIY+IWl$vbUFHa7x'
    b'Ob;VWhT&^+PHOWbiDNBGpq`Ef9R?CaB*A4sd<ye_-s|&EAdW!&YYXFA9_2xaLCg;sp262Z{FCvZiu0RX6VvW7fe5Q03WljKCbJgN'
    b'vhB}HTOQ^b6`9RBN5D?4PYT^MCqN^z1M|Oli{8dM6M|4>`rJ^5I2A1neI0iE_wF@_a5S+n{!7@Y>rJ&ukpYnd(K2Fwi4O)@8kaL9'
    b'u^1k0yj4e(wm&e<9v!LmNda{?Aq!GapAg0frsxz?p3leo`ZW*XL*Z6NEU!nc4J2r?y_sm$&JDJ$EldZ^eCB4(qYp1l3_yo>zEU8R'
    b'Lv#Rb-1$n5pF@H0*^-U5)~7`{j+TN8z&qNa^>Ka+HxJWR`#lttS#{BI??zbu7w6=dtG+?7jOQhftV~6>u~eM1R$aD|Wa$rP)p>Le'
    b'd*xY2-Jjw2T@P-wz}-B~vs7MyP`6c{L!W7TT7U{6b3q^F(%6A_zTzx`(pXD*`ee5Q@xj){`u67L7S}_-D&#A9!hqowtZ`#?86nul'
    b'^5XX9##FBp=4MqSq0(5||ML#}LadM+K9P2@gS^!Q=A?PHx6o~@GO$5`z3v)9QOHzjL@7>*f!$f<Nxe;XMPr9}>r>x#-1-qcip<r_'
    b'izKhyQ}E`ldp{%o<tHuhI%fdq=<-i>)T{bF)TwVA(dM3Py!wZ3A=aMmwvfTK!YBwKeMuq|0)&$$_q17c!FeA6ND|a$K>th1wy``1'
    b'D<+Yq>cR>qk4J3p48<{I0?)&|-Rr;LS8zT=9T8^oOz@ivUH$&`KJ^0_GPImYk#1LIkl?iL8nL*?1>3@cov=0Rb#M1H-ZqvcLlEi;'
    b'W56oTdp|=lBDPXz9o6NZw$^+**<lJ4cxjGQMeb2tA1<Tm`X9A9CmOH*qy5g$9RClhvrp*qPr^4zrpc1|61LhO5E|fQaDG$v2~B>K'
    b'QE_IXt+`M82%1V)9N_=0)kQR`S(%B8h&kb@P9u053_sKBTo~zuutW(_3EYhROxL~Z@Z+1JJP1tmUBs=s-l$q0WRda8o8N(2J6@Cy'
    b'>Ypu)_JmC87>9r?ibiAgHs0FbkOS9WSv1PYJR-OfzdvY}d${?ZDu{opGNr%yiPz)Z;+CG#Wwskj3+qdB>x;AN^V6VNIB`d1hDDxC'
    b'^*`U|$(W3XiUHc3+*)mJ)<Dpr_&rA=KDr&#K_r<_E#eC6eb-TjTmSfpYS8cRSKlMq(FPTm9Fhra4}0%;Q3h6Te_n#mAPQ?mhNJEp'
    b'ECMl<v+mE1+kb*Zkl{IH8afYrfw|%wKEO!3-c|>qS78<bqJC%fIZo9l8|iAYGVZ-J(N>XeuOO3eEmfDu@LcWpU=Qb=tN36oPlNIl'
    b'ruBLmfqw=UKy&p(l0}i`tGXnHZ$T43$eis+n<^7#Wh{xEXfy1d?Y}ZT3bE>{Icrs&UFK$MNJg5-?DX}8Dacp6))%I^0V%0M=GVoO'
    b'g;7((+Z(Ig0M^WGuVb=JCno%9su_YAf(?2J(qi2Cfi5s4!wtn?l|(xJE43H;!`c28U12oIMZYLpni@gJgFArZ*b1I4BdQ?86wpos'
    b'y2l`p-o{#VKVw-64kCI*%tAs}1Uu#F;BbhXw&$g8$t?YFRKPC*fD0ScKk2Gh!jw8*mi0B&;Smr$(cn6;Ow8j(yaQ<s%})t`+@&71'
    b'y<OxMe36Qpn_Qin+LEk|rJ@e+8%wjxQ$tJR{dmV`(W4OpTv_mmOM}HJ*}+BSR`dsL;KOYZL08;_nR@;4oqT)(TMCo9Va3pjH1D@R'
    b'|BKBxpnHNYYOBcHXVwRwk9t<3%lV3AT}l(V;r=8tO|c|FUmUMPFjW-OToB!yA4yWmc_$J5X>R;cn0)Tt30<%4k#?lLHrwH<%quXG'
    b'KX?-luV0u!x)Z!Zk@zd&MfWoaw=0^ky@{Xv$|KoIg}b<P#}cowvx;Pc5x?Ij{NWej9$>}2kpGvbAd(V>!rgRErlH`pwekYB%0T|7'
    b'zJe@jtNDf!2)&2TFDw)AOJ@-i{s)<NyiyDqp7yKn_N(voeYiECz6*gtRGcye!9~y8>aJG`#5iz9_&~-2l&K^c#rXfT=6}#<OsY$U'
    b'()i|rn29!B2(b(K5R&$XY%>%_IqzN<=EC?x+(h@AYE9Nxy1e6#`&m1IO>8`SY<dv*YG?Ou5~96?Sktac@tw-{&RiC6t4QnDJ_wq)'
    b'F5!?t<8zeFuFBMxrr4E<-~>9Lwof=5WXoJ<rdLKqX|ul4<{amTHa<pT0X4YaW_sSew)zP<=-JwY2b^e8&keL3<O*SryEoT5Udr2_'
    b'7IZeK#Qgyzt33EU$AW(tpv0Y!t%`Vd@(PhY<sXmq)<R3Y)!g_}pMN}LiP`=kfO~7hs65l0{gt)$PyRi2v8DxsV1SDUd-S}m>UmcU'
    b'-;G!jBr~9WIH-FvWPCnssfTzNv%ed)zaMqHAF;j_SFi7c+xO|<yFC3m2D@{RT}}4bWptn28bztb?djv@6y0!h{%HiEG_~dBLiKT1'
    b'lc^-uUi0<Z{4}*JswleOR9VVm9JSwv3do=({5=1gOJX1<hplfRY!*j*A#xyB5SR69A6aAxR%J3`x6QQ`D4ey08N8r#rh8o`GEXmg'
    b'*u?TbpLy^X{U6~l9Qs}aLbU7h!qWHv=x%FuDP-bMVEMrM@+4WzqMht8N-0I$Ko?q)dj)np+u6P8nXqPrZe=goTrRLV5x@T%Cz+^n'
    b'9=5zzU;igv?lECisaJY&Q66{Jmz$KCw(3hpMaH;GBc0+HYC8e?3UXmoqI<SC2lY?;n;((gX}C$K2en6$C&d?c7hgCJNXa&^UoNL4'
    b'X*lrq%I`m1{YOjncfnCVm3Q<mL7U5k?7+!2=)A5Z8LHS){jGGrppeZuceCHl$2N4@>r8$$d};_`RBzLrxxu!bT`T7Hx-9)6xP7+I'
    b'DTXl2gnv<HK;MSFv_2`EA8Z%LN8mJ@e)<DqD}n#{In3?P%d|JXFex(W!ne@f6a}NAS5V(LVk%40=ABY!AJdRrC3&f{k85*J8H!`@'
    b'!dFc<j;OPa;LN7$Uwyd#Wz+RPLVqGyLnO%b|1aVQ!tK^5-OOh%?GbX$uWXq7ZYK-VqxMEb0pP}+y|zQ=;$jcC&kvpI&+oT$fGv4L'
    b'ned-!BYh#6v%NUlvoPATwlKAG_*IbN`KSc4HRT~U2m5F1oCn+|P{^(v@U_41W(YO3#pxk){g_Mb71oqdtDoz4b-%3{GQRZrJ~A@m'
    b'-h@mf>zBDD%p)uKKz8oxUmWdT8195BnC)}T_Bv*J?K9n$=`Pb$hjFSyPlY9X2b=%-*)40I-TwI*FMeT1WkHRHaHd2ydqSfAzcvTQ'
    b'sS*DtZ%rKZFH`vbWmCtm{BIpflSm<{^^g3@AH05?(e<xqFW!CrB?ShCznZ>!fPeMl0RObjzo1A>+@*i#@cLhxt6^IyG8|I*c%%bE'
    b'LI3Q|zQQkfK#DGbp+nU^>G~SsB@T0Yf`c{Yj2IXg7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B'
    b'7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B'
    b'7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B7#J8B'
    b'7#J8n1rZFp@P~*r{5c!(cM<<5A{GD7jJR~D-~XqG-$n@a`y2fI-{t%mt^A$i-(Q=FxEImz->1U;=3kMwzoDOh6Y&qYe@aAp#P1>^'
    b'BN7i?{{Mgr{SAN3!?f}LiV*JqyNKk7m`|?1e~Y^xwvUl|`j7nQe~37TI?qH2Qn^<6BH|1_XCC<e{{{E|*ZBW$5Apn@zWxXQ`S%eC'
    b'5mC7FIj#(6KB@i>`}}^%dA~>NU*MjYd`jSJ;eX?E6v~vs*UR4cZ@B;8;{X5V5YJEQOZNBl^KT>mA9tUWh|^r(|G&6jEbgAk9XX2<'
    b'rQyi__do3O|7ZL+*Yvmi{X?JiaOL@*pKyO-EC2O3^z;7*`t~($'
)
