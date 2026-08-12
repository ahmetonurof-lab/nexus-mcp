# Active Context

## Son İşlem
- `sniper/src/fvg.py` içinde `update_fvg_states()` fonksiyonunda `filled` bayrağının yapışkan (sticky) olmamasına neden olan bug düzeltildi.
- `else` dalından `object.__setattr__(fvg, "filled", False)` kaldırıldı. Artık `filled` sadece zone içine girildiğinde `True` oluyor, dışına çıkılsa bile tekrar `False`'a dönmüyor.
- `sniper/tests/test_fvg.py`'ye `test_bullish_filled_sticky_after_zone_exit` ve `test_bearish_filled_sticky_after_zone_exit` regresyon testleri eklendi.

## İlgili Dosyalar
- `sniper/src/fvg.py`
- `sniper/tests/test_fvg.py`

## Not
- Bu fix, `FVG.mark_filled()` metodunun tek yönlü (sticky) tasarım sözleşmesi ile `update_fvg_states`'in uyumunu sağlıyor.
- `find_latest_unfilled_fvg()` seçim kriteri (`not f.filled`) artık tutarlı çalışıyor.
